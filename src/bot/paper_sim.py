import logging
import uuid
import time
from typing import List, Optional, Dict
from src.bot.execution import Executor, Order
from src.bot.risk import RiskEngine

logger = logging.getLogger("bot.paper_sim")

class PaperExecutor(Executor):
    def __init__(self, risk_engine: RiskEngine):
        self.risk_engine = risk_engine
        self.orders: Dict[str, Order] = {} # order_id -> Order
        self.fills: List[Dict] = []
        self._trade_cursors: Dict[str, int] = {}
        
    def place_order(self, token_id: str, side: str, price: float, size: float) -> Optional[Order]:
        # Risk Check
        if not self.risk_engine.check_new_order(token_id, side, size, price):
            logger.warning("Order rejected by Risk Engine")
            return None
        self.risk_engine.record_order(token_id)
            
        order_id = str(uuid.uuid4())
        order = Order(
            id=order_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            timestamp=time.time(),
            status="OPEN"
        )
        self.orders[order_id] = order
        logger.info(f"[PAPER] Placed {side} {size} @ {price} for {token_id} (ID: {order_id[:8]})")
        return order

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders and self.orders[order_id].status == "OPEN":
            self.orders[order_id].status = "CANCELED"
            logger.info(f"[PAPER] Canceled order {order_id[:8]}")
            return True
        return False
        
    def cancel_all(self, token_id: str):
        for oid, order in self.orders.items():
            if order.token_id == token_id and order.status == "OPEN":
                self.cancel_order(oid)

    def get_open_orders(self, token_id: str) -> List[Order]:
        return [o for o in self.orders.values() if o.token_id == token_id and o.status == "OPEN"]

    def process_updates(self, token_id: str, best_bid: float, best_ask: float, trades: List[Dict]):
        """
        Simulate fills based on market data.
        """
        cursor = self._trade_cursors.get(token_id, 0)
        if cursor > len(trades):
            cursor = 0
        new_trades = trades[cursor:]
        self._trade_cursors[token_id] = len(trades)

        open_orders = self.get_open_orders(token_id)
        
        for order in open_orders:
            filled = False
            fill_price = 0.0
            
            # Check immediate cross (Taker) or Passive fill via Book crossing
            # If Buy Order Price >= Best Ask, we cross -> Fill at Best Ask (or Order Price?)
            # Usually Taker fills at Best Ask.
            # But assume we placed Limit. 
            # If Best Ask moves DOWN to our Buy Price -> We get filled.
            
            if order.side == "BUY":
                # Maker Fill: Trade occurred at price <= order.price
                # Or Taker/Market Move: Best Ask <= order.price
                if best_ask <= order.price and best_ask > 0:
                     filled = True
                     fill_price = best_ask
                else:
                    # Check recent trades
                    for t in new_trades:
                        # If a trade happened at or below our price
                        if t['price'] <= order.price:
                             filled = True
                             fill_price = order.price # Limit fill
                             break
                             
            elif order.side == "SELL":
                 if best_bid >= order.price and best_bid > 0:
                     filled = True
                     fill_price = best_bid
                 else:
                     for t in new_trades:
                         if t['price'] >= order.price:
                             filled = True
                             fill_price = order.price
                             break
            
            if filled:
                logger.info(f"[PAPER] FILLED {order.side} {order.size} @ {fill_price} (Order: {order.price})")
                order.status = "FILLED"
                self.risk_engine.update_fill(token_id, order.side, order.size, fill_price)
                self.fills.append({
                    "order_id": order.id,
                    "token_id": token_id,
                    "price": fill_price,
                    "size": order.size,
                    "side": order.side,
                    "timestamp": time.time()
                })
