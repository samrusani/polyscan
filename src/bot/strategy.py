import logging
import statistics
from typing import List, Dict, Optional, Tuple

from src.infra.config import Config
from src.bot.data_feed import DataFeed

logger = logging.getLogger("bot.strategy")

class Strategy:
    def __init__(self, config: Config, data_feed: DataFeed):
        self.config = config.strategy
        self.data_feed = data_feed
        self.window = self.config.get("fair_value_window_trades", 10)
        self.epsilon = self.config.get("epsilon", 0.02)
        self.tick_size = self.config.get("tick_size", 0.01)
        self.buy_aggression_ticks = self.config.get("buy_aggression_ticks", 1)
        self.sell_offset_ticks = self.config.get("sell_offset", 5)
        self.taker_mode = self.config.get("taker_mode", False)
        self.taker_max_spread = self.config.get("taker_max_spread", 0.03)
        self.taker_min_edge = self.config.get("taker_min_edge", self.epsilon)
        
    def get_fair_value(self, token_id: str) -> Optional[float]:
        trades = self.data_feed.get_trades(token_id)
        if not trades:
            # Fallback to mid if no trades?
            ob = self.data_feed.get_orderbook(token_id)
            if ob and ob['bids'] and ob['asks']:
                best_bid = float(ob['bids'][0]['price'])
                best_ask = float(ob['asks'][0]['price'])
                return (best_bid + best_ask) / 2
            return None
            
        recent_trades = trades[-self.window:]
        prices = [t['price'] for t in recent_trades]
        if not prices:
            return None
        return statistics.mean(prices)

    def get_signal(self, token_id: str) -> str:
        """
        Returns 'BUY_YES', 'BUY_NO', or 'NEUTRAL'
        Based on user logic: "if mid > fair + epsilon accumulate YES else accumulate NO"
        (Interpreting exactly as written for "Accumulate Winner" momentum logic)
        """
        return self.get_signal_details(token_id)["signal"]

    def get_signal_details(self, token_id: str) -> Dict[str, Optional[float | str]]:
        fair = self.get_fair_value(token_id)
        ob = self.data_feed.get_orderbook(token_id)

        if fair is None or not ob or not ob['bids'] or not ob['asks']:
            return {"signal": "NEUTRAL", "fair": None, "mid": None, "edge": None}

        best_bid = float(ob['bids'][0]['price'])
        best_ask = float(ob['asks'][0]['price'])
        mid = (best_bid + best_ask) / 2
        edge = abs(mid - fair)

        # User Logic: simple skew
        if mid > fair + self.epsilon:
            signal = "BUY_YES"
        elif mid < fair - self.epsilon:
            signal = "BUY_NO"
        else:
            signal = "NEUTRAL"

        return {"signal": signal, "fair": fair, "mid": mid, "edge": edge}
    
    def get_quote_params(self, token_id: str, signal: str, edge: Optional[float] = None) -> Tuple[float, float]:
        """
        Returns (bid_price, ask_price) or (None, None)
        """
        ob = self.data_feed.get_orderbook(token_id)
        if not ob or not ob['bids'] or not ob['asks']:
            return None, None

        best_bid = float(ob['bids'][0]['price'])
        best_ask = float(ob['asks'][0]['price'])
        
        aggression = self.buy_aggression_ticks * self.tick_size
        sell_offset = self.sell_offset_ticks * self.tick_size
        spread = best_ask - best_bid
        edge_val = edge or 0.0
        taker_ok = self.taker_mode and edge_val >= self.taker_min_edge and spread <= self.taker_max_spread
        
        # If BUY_YES (Accumulate this token):
        # Aggressive Buy: Best Bid + tick? Or Mid?
        # User: "skew quotes: aggressive buy, passive sell at premium"
        
        if signal == "BUY_YES":
            if taker_ok:
                my_bid = best_ask
            else:
                my_bid = best_bid + aggression
            my_ask = best_ask + sell_offset
        elif signal == "BUY_NO":
            # Which means Sell YES? 
            # If we are quoting YES token:
            my_bid = best_bid - sell_offset
            if taker_ok:
                my_ask = best_bid
            else:
                my_ask = best_ask - aggression
        else:
            # Neutral - width?
            my_bid = best_bid
            my_ask = best_ask

        # Safety: don't cross
        if my_bid >= my_ask:
            my_bid = my_ask - 0.01
            
        # Clamp Logic
        my_bid = max(0.00, min(0.99, my_bid))
        my_ask = max(0.01, min(1.00, my_ask))
            
        return my_bid, my_ask
