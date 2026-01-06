import logging
import statistics
import time
from datetime import datetime, timezone
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderBookSummary

from src.scanner.market_discovery import Market
from src.infra.config import Config

logger = logging.getLogger("scanner.ranking")

class MarketRanker:
    def __init__(self, config: Config):
        self.config = config
        self.scanner_config = config.scanner
        self.client = ClobClient("https://clob.polymarket.com") # Public client
        
    def rank_markets(self, markets: List[Market]) -> List[Market]:
        logger.info(f"Ranking {len(markets)} markets...")
        
        ranked_markets = []
        
        # We can fetch metrics in parallel
        # Reduced max_workers to 3 to avoid rate limits
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_market = {executor.submit(self._fetch_market_metrics, m): m for m in markets}
            
            for future in as_completed(future_to_market):
                market = future_to_market[future]
                try:
                    updated_market = future.result()
                    if self._passes_filters(updated_market):
                        self._score_market(updated_market)
                        ranked_markets.append(updated_market)
                except Exception as e:
                    # Log as debug to start, only warning if critical? 
                    # Actually keeping warning is fine if it failed all retries.
                    logger.warning(f"Failed to process market {market.id}: {e}")
        
        # Sort by rank score descending
        ranked_markets.sort(key=lambda m: m.rank_score, reverse=True)
        
        top_n = self.scanner_config.get("top_n", 10)
        return ranked_markets[:top_n]

    def _fetch_market_metrics(self, market: Market) -> Market:
        token_id = market.yes_token_id or (market.clob_token_ids[0] if market.clob_token_ids else None)
        if not token_id:
            raise ValueError("No token ID available for order book lookup")
        
        retries = 3
        last_exception = None
        
        for attempt in range(retries):
            try:
                ob = self.client.get_order_book(token_id)
                # ob has bids, asks as lists of objects {price, size}
                
                best_bid = float(ob.bids[0].price) if ob.bids else 0.0
                best_ask = float(ob.asks[0].price) if ob.asks else 1.0
                
                market.spread = best_ask - best_bid
                
                mid = (best_bid + best_ask) / 2
                
                depth = 0.0
                for level in ob.bids:
                    p = float(level.price)
                    if p >= mid - 0.05:
                        depth += float(level.size) * p
                for level in ob.asks:
                    p = float(level.price)
                    if p <= mid + 0.05:
                        depth += float(level.size) * p
                        
                market.depth_usd = depth
                if market.time_to_settlement_sec is None:
                    tz = market.end_date.tzinfo or timezone.utc
                    market.time_to_settlement_sec = max(
                        0.0, (market.end_date - datetime.now(tz)).total_seconds()
                    )

                recent_trades, volatility = self._fetch_recent_trades(token_id)
                if recent_trades is not None:
                    market.recent_trades = recent_trades
                if volatility is not None:
                    market.volatility = volatility
                return market

            except Exception as e:
                last_exception = e
                # Exponential backoff
                time.sleep(1 * (2 ** attempt))
                continue
        
        raise last_exception

    def _fetch_recent_trades(self, token_id: str) -> tuple[Optional[int], Optional[float]]:
        limit = self.scanner_config.get("recent_trades_lookback", 50)
        trades = None

        if hasattr(self.client, "get_trades"):
            try:
                trades = self.client.get_trades(token_id=token_id, limit=limit)
            except TypeError:
                try:
                    trades = self.client.get_trades(token_id, limit)
                except Exception:
                    trades = None
            except Exception:
                trades = None

        if trades is None:
            return None, None

        if isinstance(trades, dict):
            trades = trades.get("data") or trades.get("trades") or []

        if not isinstance(trades, list):
            return None, None

        prices = []
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            price = trade.get("price")
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            prices.append(price)

        if not prices:
            return 0, None

        volatility = statistics.pstdev(prices) if len(prices) > 1 else 0.0
        return len(prices), volatility

    def _passes_filters(self, market: Market) -> bool:
        if market.spread is None: 
            logger.info(f"Market {market.id} filtered: No spread")
            return False
        
        max_spread = self.scanner_config.get("max_spread", 0.05)
        if market.spread > max_spread:
            logger.info(f"Market {market.id} filtered: Spread {market.spread:.4f} > {max_spread}")
            return False
            
        min_depth = self.scanner_config.get("min_depth_near_mid", 100)
        if (market.depth_usd or 0) < min_depth:
            logger.info(f"Market {market.id} filtered: Depth {market.depth_usd} < {min_depth}")
            return False

        min_recent_trades = self.scanner_config.get("min_recent_trades")
        if market.recent_trades is not None and min_recent_trades is not None:
            if market.recent_trades < min_recent_trades:
                logger.info(
                    f"Market {market.id} filtered: Recent trades {market.recent_trades} < {min_recent_trades}"
                )
                return False
            
        return True

    def _score_market(self, market: Market):
        # Higher score = better
        # Prefer tight spread, high volume, approaching settlement
        # Simple score
        spread_score = 1.0 / (market.spread + 0.001)
        volume_score = (market.volume_usd or 0) / 1000.0
        depth_score = (market.depth_usd or 0) / 100.0

        trades_target = self.scanner_config.get("recent_trades_target", 20)
        trades_score = 0.0
        if market.recent_trades is not None and trades_target:
            trades_score = min(market.recent_trades / trades_target, 1.0)

        volatility_target = self.scanner_config.get("volatility_target", 0.05)
        volatility_score = 0.0
        if market.volatility is not None and volatility_target:
            volatility_score = min(market.volatility / volatility_target, 1.0)
        close_window = self.scanner_config.get("volatility_close_window_sec", 0)
        close_floor = self.scanner_config.get("volatility_close_floor", 0.0)
        if close_window and market.time_to_settlement_sec is not None:
            if market.time_to_settlement_sec <= close_window:
                volatility_score = max(volatility_score, min(close_floor, 1.0))

        time_target = self.scanner_config.get("target_time_to_settlement_sec", 86400)
        time_score = 0.0
        if market.time_to_settlement_sec is not None and time_target:
            delta = abs(market.time_to_settlement_sec - time_target)
            time_score = 1.0 / (1.0 + (delta / time_target))

        weight_spread = self.scanner_config.get("weight_spread", 0.4)
        weight_volume = self.scanner_config.get("weight_volume", 0.1)
        weight_depth = self.scanner_config.get("weight_depth", 0.2)
        weight_trades = self.scanner_config.get("weight_recent_trades", 0.1)
        weight_volatility = self.scanner_config.get("weight_volatility", 0.1)
        weight_time = self.scanner_config.get("weight_time_to_settlement", 0.1)

        market.rank_score = (
            spread_score * weight_spread
            + volume_score * weight_volume
            + depth_score * weight_depth
            + trades_score * weight_trades
            + volatility_score * weight_volatility
            + time_score * weight_time
        )
