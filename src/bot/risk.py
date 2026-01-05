import logging
from typing import Dict, List, Tuple
from datetime import datetime, timedelta

from src.infra.config import Config

logger = logging.getLogger("bot.risk")

class RiskEngine:
    def __init__(self, config: Config):
        self.config = config.risk
        self.inventory: Dict[str, float] = {} # token_id -> quantity (signed?) usually Inventory is Net Position
        self.daily_pnl = 0.0
        self.open_orders_count = 0
        self.market_pnl: Dict[str, float] = {}
        self.last_flatten_time: Dict[str, datetime] = {}
        self.last_order_time: Dict[str, datetime] = {}
        
    def check_new_order(self, token_id: str, side: str, qty: float, price: float) -> bool:
        # Check Daily Loss
        daily_max = self.config.get("daily_max_loss_usd", 50.0)
        if self.daily_pnl < -daily_max:
            logger.warning(f"Risk Reject: Daily Max Loss exceeded ({self.daily_pnl} < -{daily_max})")
            return False

        # Check Market Loss
        market_max = self.config.get("market_max_loss_usd", 10.0)
        if self.market_pnl.get(token_id, 0) < -market_max:
            logger.warning(f"Risk Reject: Market Max Loss exceeded for {token_id}")
            return False
            
        # Check Inventory Limits
        # If buying, will inv > max?
        # If selling, will inv < -max?
        current_inv = self.inventory.get(token_id, 0)
        max_inv = self.config.get("max_total_inventory", 100)
        
        if side.upper() == "BUY":
            if current_inv + qty > max_inv:
                logger.warning(f"Risk Reject: Max Inventory Exceeded {current_inv} + {qty} > {max_inv}")
                return False
        elif side.upper() == "SELL":
            if current_inv - qty < -max_inv:
                logger.warning(f"Risk Reject: Min Inventory Exceeded {current_inv} - {qty} < -{max_inv}")
                return False
                
        # Check Cooldown
        cooldown = self.config.get("cooldown_after_flip_sec", 60)
        last_flat = self.last_flatten_time.get(token_id)
        if last_flat:
             if (datetime.utcnow() - last_flat).total_seconds() < cooldown:
                 logger.warning("Risk Reject: Cooldown active")
                 return False

        # Check per-market order throttle
        throttle_sec = self.config.get("market_order_throttle_sec", 0)
        last_order = self.last_order_time.get(token_id)
        if last_order and throttle_sec > 0:
            if (datetime.utcnow() - last_order).total_seconds() < throttle_sec:
                logger.warning("Risk Reject: Order throttle active")
                return False

        return True

    def record_order(self, token_id: str):
        self.last_order_time[token_id] = datetime.utcnow()

    def update_fill(self, token_id: str, side: str, qty: float, price: float):
        current_inv = self.inventory.get(token_id, 0)
        if side.upper() == "BUY":
            self.inventory[token_id] = current_inv + qty
        else:
            self.inventory[token_id] = current_inv - qty
            
        # PnL tracking is complex without avg cost. 
        # For simple risk, we track Realized PnL? 
        # Or Mark-to-Market?
        # Let's assume MTM is handled in Portfolio/Metrics, 
        # but Risk needs "Daily Loss".
        # We'll update PnL nicely in a separate method `update_pnl(val)` called by portfolio.
        pass

    def update_pnl(self, token_id: str, realized_pnl: float, unrealized_pnl: float):
        # Update trackers
        # Note: simplistic addition of realized.
        # Ideally we snapshot total equity.
        self.market_pnl[token_id] = realized_pnl + unrealized_pnl
        # Global daily pnl is sum of all markets?
        self.daily_pnl = sum(self.market_pnl.values())

    def get_limit_breaches(self) -> Tuple[bool, List[str]]:
        daily_max = self.config.get("daily_max_loss_usd", 50.0)
        market_max = self.config.get("market_max_loss_usd", 10.0)

        halt_all = self.daily_pnl < -daily_max
        market_breaches = [tid for tid, pnl in self.market_pnl.items() if pnl < -market_max]

        return halt_all, market_breaches

    def trigger_flatten(self, token_id: str):
        self.last_flatten_time[token_id] = datetime.utcnow()
        self.inventory[token_id] = 0 # Assume flattened
        logger.warning(f"Flatten triggered for {token_id}")
