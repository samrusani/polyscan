import logging
import time
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

from src.bot.execution import Executor, Order
from src.bot.risk import RiskEngine
from src.infra.retry import call_with_retries

logger = logging.getLogger("bot.live")

class LiveExecutor(Executor):
    def __init__(self, risk_engine: RiskEngine, config: dict):
        self.risk_engine = risk_engine
        self.config = config
        self._seen_fill_ids = set()
        self._last_fill_ts = 0.0
        self._order_cache: Dict[str, Order] = {}
        self._last_order_refresh = 0.0
        
        # Load Env
        key = os.getenv("CLOB_API_KEY")
        chain_id = int(os.getenv("CLOB_CHAIN_ID", "137"))
        
        if not key:
            raise ValueError("CLOB_API_KEY not found in env for Live Trading")
            
        self.client = ClobClient("https://clob.polymarket.com", key=key, chain_id=chain_id)
        self._retry_attempts = int(self.config.get("execution", {}).get("order_retry_attempts", 3))
        self._retry_backoff = float(self.config.get("execution", {}).get("order_retry_backoff_sec", 1))
        
    def place_order(self, token_id: str, side: str, price: float, size: float) -> Optional[Order]:
        if not self.risk_engine.check_new_order(token_id, side, size, price):
            logger.warning("Live Order rejected by Risk Engine")
            return None
        self.risk_engine.record_order(token_id)
            
        try:
            # Place Order
            # side: BUY/SELL
            # py-clob-client uses string "BUY" or "SELL" for side in OrderArgs
            clob_side = "BUY" if side.upper() == "BUY" else "SELL"
            
            def _place():
                return self.client.create_and_post_order(
                    OrderArgs(
                        price=price,
                        size=size,
                        side=clob_side,
                        token_id=token_id
                    )
                )
            resp = call_with_retries(_place, self._retry_attempts, self._retry_backoff)
            # Response handling relies on client version. Assuming it returns order ID or obj.
            order_id = resp.get("orderID") or resp.get("id")
            if not order_id:
                logger.error(f"Live Order failed: {resp}")
                return None
                
            logger.info(f"[LIVE] Placed {side} {size} @ {price} (ID: {order_id})")
            
            order = Order(
                id=order_id,
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                timestamp=time.time(),
                status="OPEN"
            )
            self._order_cache[order_id] = order
            return order

        except Exception as e:
            logger.exception(f"Live Order Error: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        try:
            def _cancel():
                return self.client.cancel(order_id)
            call_with_retries(_cancel, self._retry_attempts, self._retry_backoff)
            logger.info(f"[LIVE] Canceled {order_id}")
            if order_id in self._order_cache:
                self._order_cache[order_id].status = "CANCELED"
            return True
        except Exception as e:
            logger.error(f"Live Cancel Error: {e}")
            return False

    def cancel_all(self, token_id: str):
         try:
             def _cancel_all():
                 return self.client.cancel_all(token_id=token_id)
             call_with_retries(_cancel_all, self._retry_attempts, self._retry_backoff)
             logger.info(f"[LIVE] Canceled all for {token_id}")
             for order in self._order_cache.values():
                 if order.token_id == token_id and order.status == "OPEN":
                     order.status = "CANCELED"
         except Exception as e:
             logger.error(f"Live Cancel All Error: {e}")

    def get_open_orders(self, token_id: str) -> List[Order]:
        cache_enabled = self.config.get("execution", {}).get("live_order_cache_enabled", True)
        if cache_enabled:
            cached = [
                o for o in self._order_cache.values()
                if o.token_id == token_id and o.status == "OPEN"
            ]
            if cached:
                return cached

        # Fetch actual open orders
        try:
            def _fetch():
                return self.client.get_open_orders(token_id=token_id)
            orders = call_with_retries(_fetch, self._retry_attempts, self._retry_backoff)
            # Map to Order objects
            res = []
            for o in orders:
                order = Order(
                    id=o.get("orderID") or o.get("id"),
                    token_id=o.get("tokenID"),
                    side="BUY" if o.get("side") == "BUY" else "SELL",
                    price=float(o.get("price")),
                    size=float(o.get("size")),
                    timestamp=0, # Unknown
                    status="OPEN"
                )
                res.append(order)
                if order.id:
                    self._order_cache[order.id] = order
            return res
        except Exception as e:
            logger.error(f"Live Get Orders Error: {e}")
            return []

    def refresh_open_orders(self, token_ids: List[str], min_interval_sec: int = 30):
        now = time.time()
        if now - self._last_order_refresh < min_interval_sec:
            return
        self._last_order_refresh = now

        for token_id in token_ids:
            try:
                def _fetch():
                    return self.client.get_open_orders(token_id=token_id)
                orders = call_with_retries(_fetch, self._retry_attempts, self._retry_backoff)
            except Exception:
                continue

            live_ids = set()
            for o in orders:
                order = Order(
                    id=o.get("orderID") or o.get("id"),
                    token_id=o.get("tokenID"),
                    side="BUY" if o.get("side") == "BUY" else "SELL",
                    price=float(o.get("price")),
                    size=float(o.get("size")),
                    timestamp=0,
                    status="OPEN"
                )
                if order.id:
                    live_ids.add(order.id)
                    self._order_cache[order.id] = order

            # Mark cached orders for this token that are no longer open
            for order in self._order_cache.values():
                if order.token_id == token_id and order.status == "OPEN" and order.id not in live_ids:
                    order.status = "CLOSED"

    def get_cached_open_orders(self) -> List[Order]:
        return [o for o in self._order_cache.values() if o.status == "OPEN"]

    def get_order_cache_state(self) -> Dict[str, Any]:
        return {
            "last_refresh_ts": self._last_order_refresh or None,
            "cache_size": len(self._order_cache)
        }

    def poll_fills(self, limit: int = 100) -> List[Dict[str, Any]]:
        fetchers = [
            ("get_fills", {"limit": limit}),
            ("get_user_trades", {"limit": limit}),
            ("get_trades", {"limit": limit}),
            ("get_user_fills", {"limit": limit})
        ]

        response = None
        for method_name, kwargs in fetchers:
            if not hasattr(self.client, method_name):
                continue
            try:
                response = getattr(self.client, method_name)(**kwargs)
                break
            except TypeError:
                try:
                    response = getattr(self.client, method_name)(limit)
                    break
                except Exception:
                    continue
            except Exception:
                continue

        if response is None:
            return []

        fills = self._extract_fill_list(response)
        normalized = []
        for raw in fills:
            fill = self._normalize_fill(raw)
            if not fill:
                continue
            fill_id = fill.get("fill_id")
            fingerprint = fill_id or f"{fill.get('order_id')}-{fill.get('token_id')}-{fill.get('price')}-{fill.get('size')}-{fill.get('timestamp')}"
            timestamp = fill.get("timestamp", 0.0)
            if timestamp and timestamp < self._last_fill_ts:
                continue
            if fingerprint in self._seen_fill_ids:
                continue
            normalized.append(fill)
            self._seen_fill_ids.add(fingerprint)
            if timestamp and timestamp > self._last_fill_ts:
                self._last_fill_ts = timestamp
            order_id = fill.get("order_id")
            if order_id and order_id in self._order_cache:
                self._order_cache[order_id].status = "FILLED"

        # Avoid unbounded growth
        if len(self._seen_fill_ids) > 5000:
            self._seen_fill_ids = set(list(self._seen_fill_ids)[-2500:])

        return normalized

    @staticmethod
    def _extract_fill_list(response: Any) -> List[Dict[str, Any]]:
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            for key in ("data", "fills", "trades", "results"):
                if key in response and isinstance(response[key], list):
                    return response[key]
        return []

    @staticmethod
    def _normalize_fill(raw: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None

        def _get_first(keys, default=None):
            for key in keys:
                if key in raw:
                    return raw.get(key)
            return default

        token_id = _get_first(["token_id", "tokenID", "asset_id", "assetId", "clob_token_id"])
        price = _get_first(["price", "fillPrice", "rate"])
        size = _get_first(["size", "qty", "quantity", "filledSize"])
        side = _get_first(["side", "takerSide"])
        order_id = _get_first(["order_id", "orderID", "orderId", "id"])
        fill_id = _get_first(["fill_id", "fillID", "trade_id", "tradeID", "id"])
        timestamp = _get_first(["timestamp", "created_at", "createdAt", "time", "ts"])

        try:
            price = float(price)
            size = float(size)
        except (TypeError, ValueError):
            return None

        if not token_id or not side or price <= 0 or size <= 0:
            return None

        side = str(side).upper()
        if side not in ("BUY", "SELL"):
            return None

        ts = None
        if isinstance(timestamp, (int, float)):
            ts = float(timestamp)
            if ts > 1e12:
                ts = ts / 1000.0
        elif isinstance(timestamp, str):
            try:
                ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
            except Exception:
                ts = None

        if ts is None:
            ts = time.time()

        return {
            "fill_id": str(fill_id) if fill_id else None,
            "order_id": str(order_id) if order_id else None,
            "token_id": str(token_id),
            "price": price,
            "size": size,
            "side": side,
            "timestamp": ts
        }
