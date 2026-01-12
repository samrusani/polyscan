import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests

logger = logging.getLogger("market_data.spot_feed")


class SpotPriceFeed:
    def __init__(self, config: Dict[str, object]):
        self.provider = str(config.get("provider", "binance")).lower()
        self.lookback_minutes = int(config.get("lookback_minutes", 60))
        self.timeout_sec = int(config.get("timeout_sec", 10))
        self.binance_base_url = str(config.get("binance_base_url", "https://api.binance.com"))
        self.coinbase_base_url = str(config.get("coinbase_base_url", "https://api.exchange.coinbase.com"))

    def get_recent_prices(self, symbol: str) -> List[float]:
        symbol = symbol.upper()
        if self.provider == "coinbase":
            return self._fetch_coinbase_prices(symbol)
        return self._fetch_binance_prices(symbol)

    def _fetch_binance_prices(self, symbol: str) -> List[float]:
        pair = _binance_pair(symbol)
        if not pair:
            logger.warning("Binance pair not found for symbol %s", symbol)
            return []
        url = f"{self.binance_base_url}/api/v3/klines"
        params = {
            "symbol": pair,
            "interval": "1m",
            "limit": self.lookback_minutes
        }
        try:
            resp = requests.get(url, params=params, timeout=self.timeout_sec)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Binance price fetch failed: %s", exc)
            return []
        data = resp.json()
        prices = []
        for row in data:
            if not isinstance(row, list) or len(row) < 5:
                continue
            try:
                prices.append(float(row[4]))
            except (TypeError, ValueError):
                continue
        return prices

    def _fetch_coinbase_prices(self, symbol: str) -> List[float]:
        product = _coinbase_product(symbol)
        if not product:
            logger.warning("Coinbase product not found for symbol %s", symbol)
            return []
        url = f"{self.coinbase_base_url}/products/{product}/candles"
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=self.lookback_minutes)
        params = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "granularity": 60
        }
        try:
            resp = requests.get(url, params=params, timeout=self.timeout_sec)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Coinbase price fetch failed: %s", exc)
            return []
        data = resp.json()
        prices = []
        for row in data:
            if not isinstance(row, list) or len(row) < 5:
                continue
            try:
                prices.append(float(row[4]))
            except (TypeError, ValueError):
                continue
        prices.reverse()
        return prices


def _binance_pair(symbol: str) -> str | None:
    if symbol == "BTC":
        return "BTCUSDT"
    if symbol == "ETH":
        return "ETHUSDT"
    if symbol == "SOL":
        return "SOLUSDT"
    if symbol == "XRP":
        return "XRPUSDT"
    return None


def _coinbase_product(symbol: str) -> str | None:
    if symbol == "BTC":
        return "BTC-USD"
    if symbol == "ETH":
        return "ETH-USD"
    if symbol == "SOL":
        return "SOL-USD"
    if symbol == "XRP":
        return "XRP-USD"
    return None
