import logging
import asyncio
import json
try:
    import websockets
except ImportError:
    websockets = None
from typing import List, Callable, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("bot.data_feed")

class DataFeed:
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self, token_ids: List[str]):
        self.token_ids = token_ids
        self.callbacks: List[Callable[[Dict], None]] = []
        self.running = False
        self.orderbooks: Dict[str, Dict] = {} # token_id -> {bids: [], asks: []}
        self.trades: Dict[str, List] = {t: [] for t in token_ids}
        self._task = None

    async def start(self):
        self.running = True
        self._task = asyncio.create_task(self._connect_and_listen())
        logger.info("DataFeed started.")

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DataFeed stopped.")

    def subscribe(self, callback: Callable[[Dict], None]):
        self.callbacks.append(callback)

    async def _connect_and_listen(self):
        if websockets is None:
            raise RuntimeError("websockets is required for live data feed. Install it via requirements.txt.")
        while self.running:
            try:
                async with websockets.connect(self.WS_URL) as ws:
                    logger.info(f"Connected to {self.WS_URL}")
                    
                    # Subscribe
                    payload = {
                        "assets_ids": self.token_ids,
                        "type": "market"
                    }
                    await ws.send(json.dumps(payload))
                    logger.info(f"Subscribed to {len(self.token_ids)} assets")

                    async for message in ws:
                        if not self.running: break
                        data = json.loads(message)
                        self._handle_message(data)
                        
            except Exception as e:
                logger.error(f"WS Error: {e}")
                await asyncio.sleep(5) # Backoff

    def _handle_message(self, data: List[Dict] | Dict):
        # Data might be a list of events or single event
        if isinstance(data, list):
            for item in data:
                self._process_event(item)
        else:
            self._process_event(data)

    def _process_event(self, event: Dict):
        event_type = event.get("event_type")
        asset_id = event.get("asset_id")
        
        if event_type == "book":
            # Update local book
            # event has "bids", "asks", "hash"
            # It seems to be a snapshot-like update or we treat it as such for now?
            # CLOB WS usually sends 'price', 'size'.
            # We'll just store it as the current book.
            bids = self._normalize_book_side(event.get("bids", []), descending=True)
            asks = self._normalize_book_side(event.get("asks", []), descending=False)
            self.orderbooks[asset_id] = {
                "bids": bids,
                "asks": asks,
                "timestamp": datetime.utcnow().isoformat()
            }
            # Notify
            self._notify(event)
            
        elif event_type == "last_trade_price":
            # Trade update
            price = event.get("price")
            size = event.get("size")
            side = event.get("side")
            trade = {
                "price": float(price) if price else 0,
                "size": float(size) if size else 0,
                "side": side,
                "timestamp": datetime.utcnow().isoformat()
            }
            if asset_id in self.trades:
                self.trades[asset_id].append(trade)
                # Keep last 100
                if len(self.trades[asset_id]) > 100:
                    self.trades[asset_id].pop(0)
            
            self._notify(event)

    def _notify(self, event: Dict):
        for cb in self.callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        return self.orderbooks.get(token_id)

    def get_trades(self, token_id: str) -> List[Dict]:
        return self.trades.get(token_id, [])

    @staticmethod
    def _normalize_book_side(levels: List[Dict], descending: bool) -> List[Dict]:
        normalized = []
        for level in levels:
            if not isinstance(level, dict):
                continue
            try:
                price = float(level.get("price"))
                size = float(level.get("size"))
            except (TypeError, ValueError):
                continue
            if size <= 0:
                continue
            normalized.append({"price": price, "size": size})
        normalized.sort(key=lambda x: x["price"], reverse=descending)
        return normalized
