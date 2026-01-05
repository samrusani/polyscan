import json
import time
import logging
import urllib.request
from typing import Optional, Dict


class AlertManager:
    def __init__(self, config: Dict, logger: Optional[logging.Logger] = None):
        self.enabled = config.get("enable", False)
        self.mode = config.get("mode", "webhook")
        self.webhook_url = config.get("webhook_url", "")
        self.min_interval = config.get("min_interval_sec", 60)
        self.pnl_threshold = config.get("pnl_alert_threshold_usd", 100.0)
        self.stale_recon_multiplier = config.get("stale_recon_multiplier", 3)
        self._last_sent = 0.0
        self.logger = logger or logging.getLogger("bot.alerts")

    def _can_send(self) -> bool:
        return time.time() - self._last_sent >= self.min_interval

    def _send(self, payload: Dict) -> bool:
        if not self.enabled or not self._can_send():
            return False
        if self.mode == "log":
            self.logger.warning(f"ALERT {payload.get('type')}: {payload.get('message')} | {payload.get('extra')}")
            self._last_sent = time.time()
            return True
        if self.mode != "webhook" or not self.webhook_url:
            return False
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if 200 <= resp.status < 300:
                    self._last_sent = time.time()
                    return True
        except Exception:
            return False
        return False

    def alert_risk(self, message: str, extra: Optional[Dict] = None) -> bool:
        payload = {"type": "risk", "message": message, "extra": extra or {}}
        return self._send(payload)

    def alert_pnl(self, total_pnl: float) -> bool:
        if abs(total_pnl) < self.pnl_threshold:
            return False
        payload = {"type": "pnl", "message": "PnL threshold breached", "extra": {"total_pnl": total_pnl}}
        return self._send(payload)

    def alert_stale(self, last_poll_ts: float, poll_interval: float) -> bool:
        if not last_poll_ts:
            return False
        max_age = poll_interval * self.stale_recon_multiplier
        if time.time() - last_poll_ts <= max_age:
            return False
        payload = {
            "type": "stale_recon",
            "message": "Live reconciliation poll is stale",
            "extra": {"last_poll_ts": last_poll_ts, "poll_interval": poll_interval}
        }
        return self._send(payload)
