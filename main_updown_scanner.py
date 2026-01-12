import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from typing import Dict, Optional, Tuple

from py_clob_client.client import ClobClient

from src.infra.config import load_config
from src.infra.logger import setup_logger
from src.market_data.spot_feed import SpotPriceFeed
from src.market_data.updown_model import UpDownFairValueModel
from src.scanner.updown_scanner import UpDownMarket, UpDownMarketDiscovery

logger = setup_logger("updown_scanner")


def _fetch_orderbook_mid(client: ClobClient, token_id: str) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    try:
        ob = client.get_order_book(token_id)
    except Exception as exc:
        logger.warning("Orderbook fetch failed for %s: %s", token_id, exc)
        return None, None, None, None

    bids = getattr(ob, "bids", []) or []
    asks = getattr(ob, "asks", []) or []
    if not bids or not asks:
        return None, None, None, None

    def _price(level: object) -> Optional[float]:
        if isinstance(level, dict):
            value = level.get("price")
        else:
            value = getattr(level, "price", None)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    best_bid = _price(bids[0])
    best_ask = _price(asks[0])
    if best_bid is None or best_ask is None:
        return None, None, None, None
    mid = (best_bid + best_ask) / 2.0
    spread = best_ask - best_bid
    return best_bid, best_ask, mid, spread


def _compute_recommendation(market: UpDownMarket, min_edge: float) -> None:
    best_side = None
    best_edge = None
    if market.edge_up is not None and market.edge_up > 0:
        best_side = "UP"
        best_edge = market.edge_up
    if market.edge_down is not None and market.edge_down > 0:
        if best_edge is None or market.edge_down > best_edge:
            best_side = "DOWN"
            best_edge = market.edge_down

    market.edge_best = best_edge
    if best_edge is None or best_edge < min_edge:
        market.recommended_side = "NEUTRAL"
    else:
        market.recommended_side = f"BUY_{best_side}"


def main() -> None:
    logger.info("Starting Up/Down Scanner...")

    config = load_config()
    scanner_cfg = config.updown_scanner
    feed_cfg = config.price_feed

    discovery = UpDownMarketDiscovery(scanner_cfg)
    markets = discovery.fetch_markets()
    if not markets:
        logger.warning("No up/down markets found.")
        return

    price_feed = SpotPriceFeed(feed_cfg)
    model = UpDownFairValueModel(
        min_samples=int(scanner_cfg.get("min_return_samples", 30)),
        clamp_min=float(scanner_cfg.get("probability_clamp_min", 0.01)),
        clamp_max=float(scanner_cfg.get("probability_clamp_max", 0.99))
    )

    asset_stats: Dict[str, object] = {}
    asset_prices: Dict[str, list] = {}
    for market in markets:
        symbol = market.asset_symbol
        if symbol in asset_stats:
            continue
        prices = price_feed.get_recent_prices(symbol)
        asset_prices[symbol] = prices
        asset_stats[symbol] = model.fit(prices) if prices else None
        if asset_stats[symbol] is None:
            logger.warning("No return stats for %s (price samples: %s).", symbol, len(prices))

    client = ClobClient("https://clob.polymarket.com")
    min_edge = float(scanner_cfg.get("min_edge", 0.02))

    evaluated: list[UpDownMarket] = []
    for market in markets:
        stats = asset_stats.get(market.asset_symbol)
        if stats is None or market.time_to_settlement_sec is None:
            continue

        prob_up = model.probability_up(stats, market.time_to_settlement_sec)
        if prob_up is None:
            continue
        prob_down = 1.0 - prob_up

        market.model_prob_up = prob_up
        market.model_prob_down = prob_down
        market.model_return_mean = stats.mean
        market.model_return_stdev = stats.stdev
        market.model_return_samples = stats.samples
        prices = asset_prices.get(market.asset_symbol) or []
        market.spot_price = prices[-1] if prices else None

        if not market.up_token_id and not market.down_token_id and market.yes_token_id and market.no_token_id:
            if market.is_range_market:
                continue
            direction = market.direction_hint
            target = market.target_price
            if direction is None and target is not None and market.spot_price is not None:
                if target > market.spot_price:
                    direction = "UP"
                elif target < market.spot_price:
                    direction = "DOWN"
            if direction == "UP":
                market.up_token_id = market.yes_token_id
                market.down_token_id = market.no_token_id
            elif direction == "DOWN":
                market.down_token_id = market.yes_token_id
                market.up_token_id = market.no_token_id

        if not market.up_token_id or not market.down_token_id:
            continue

        if market.up_token_id:
            bid, ask, mid, spread = _fetch_orderbook_mid(client, market.up_token_id)
            market.best_bid_up = bid
            market.best_ask_up = ask
            market.mid_up = mid
            market.spread_up = spread
            if mid is not None:
                market.edge_up = prob_up - mid

        if market.down_token_id:
            bid, ask, mid, spread = _fetch_orderbook_mid(client, market.down_token_id)
            market.best_bid_down = bid
            market.best_ask_down = ask
            market.mid_down = mid
            market.spread_down = spread
            if mid is not None:
                market.edge_down = prob_down - mid

        _compute_recommendation(market, min_edge)
        if market.edge_best is not None and market.edge_best >= min_edge:
            evaluated.append(market)

    if not evaluated:
        logger.warning("No up/down markets met the min-edge threshold.")

    evaluated.sort(key=lambda m: m.edge_best or 0.0, reverse=True)
    max_markets = int(scanner_cfg.get("max_markets", 50))
    if max_markets:
        evaluated = evaluated[:max_markets]

    timestamp = datetime.utcnow().isoformat()
    output_data = {
        "generated_at": timestamp,
        "scanner_settings": {
            "min_volume_usd": scanner_cfg.get("min_volume_usd"),
            "max_duration_hours": scanner_cfg.get("max_duration_hours"),
            "max_markets": max_markets,
            "min_edge": min_edge
        },
        "price_feed": {
            "provider": price_feed.provider,
            "lookback_minutes": price_feed.lookback_minutes
        },
        "model": {
            "min_return_samples": model.min_samples,
            "probability_clamp_min": model.clamp_min,
            "probability_clamp_max": model.clamp_max,
            "assets": {
                symbol: {
                    "spot_price": (prices[-1] if prices else None),
                    "return_samples": getattr(stats, "samples", None),
                    "return_mean": getattr(stats, "mean", None),
                    "return_stdev": getattr(stats, "stdev", None)
                }
                for symbol, stats in asset_stats.items()
                for prices in [asset_prices.get(symbol, [])]
            }
        },
        "markets": [asdict(market) for market in evaluated]
    }

    def json_serial(obj: object):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    data_dir = "data"
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    output_path = scanner_cfg.get("output_path", os.path.join(data_dir, "updown_watchlist.json"))
    with open(output_path, "w") as f:
        json.dump(output_data, f, default=json_serial, indent=2)

    logger.info("Up/down watchlist written to %s", output_path)


if __name__ == "__main__":
    main()
