import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

logger = logging.getLogger("scanner.arb")


@dataclass
class ArbMarket:
    id: str
    question: str
    slug: str
    end_date: datetime
    volume_usd: float
    yes_token_id: str
    no_token_id: str
    time_to_settlement_sec: Optional[float] = None
    best_bid_yes: Optional[float] = None
    best_ask_yes: Optional[float] = None
    best_bid_yes_size: Optional[float] = None
    best_ask_yes_size: Optional[float] = None
    best_bid_no: Optional[float] = None
    best_ask_no: Optional[float] = None
    best_bid_no_size: Optional[float] = None
    best_ask_no_size: Optional[float] = None
    sum_asks: Optional[float] = None
    sum_bids: Optional[float] = None
    edge_buy_both: Optional[float] = None


class ArbMarketDiscovery:
    MARKETS_URL = "https://gamma-api.polymarket.com/markets"

    def __init__(self, config: Dict[str, object]):
        self.config = config
        self.min_volume = float(config.get("min_volume_usd", 1000))
        self.max_duration_hours = float(config.get("max_duration_hours", 168))
        self.fetch_limit = int(config.get("fetch_limit", 500))
        self.exclude_range_markets = bool(config.get("exclude_range_markets", False))

    @staticmethod
    def _normalize_outcome_name(outcome: object) -> str:
        if isinstance(outcome, dict):
            name = outcome.get("name") or outcome.get("outcome") or outcome.get("value")
        else:
            name = outcome
        return str(name).strip().lower()

    @staticmethod
    def _map_yes_no_tokens(outcomes: List[object], clob_ids: List[str]) -> tuple[Optional[str], Optional[str]]:
        if not outcomes or not clob_ids or len(outcomes) != len(clob_ids):
            return None, None

        yes_token_id = None
        no_token_id = None

        for idx, outcome in enumerate(outcomes):
            name = ArbMarketDiscovery._normalize_outcome_name(outcome)
            if name == "yes":
                yes_token_id = clob_ids[idx]
            elif name == "no":
                no_token_id = clob_ids[idx]

        return yes_token_id, no_token_id

    @staticmethod
    def _is_range_market(question: str) -> bool:
        lowered = question.lower()
        if "between" in lowered or "range" in lowered or "within" in lowered:
            return True
        import re
        return re.search(r"from\s+\$?\d.*\s+to\s+\$?\d", lowered) is not None

    def fetch_markets(self) -> List[ArbMarket]:
        logger.info("Fetching markets from Gamma API for arb scan...")
        now = datetime.now(timezone.utc)
        params = {
            "active": "true",
            "closed": "false",
            "limit": self.fetch_limit,
            "order": "volume",
            "ascending": "false"
        }
        if self.max_duration_hours:
            max_end = now + timedelta(hours=self.max_duration_hours)
            params["end_date_max"] = max_end.isoformat().replace("+00:00", "Z")

        try:
            resp = requests.get(self.MARKETS_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("Failed to fetch markets: %s", exc)
            return []

        candidates: List[ArbMarket] = []
        for item in data:
            try:
                if not item.get("active") or item.get("closed"):
                    continue

                vol = float(item.get("volume", 0) or 0)
                if vol < self.min_volume:
                    continue

                end_date_str = item.get("endDate")
                if not end_date_str:
                    continue
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                time_to_settlement = (end_date - now).total_seconds()
                if time_to_settlement <= 0:
                    continue

                outcomes = _parse_list_field(item.get("outcomes"))
                clob_ids = _parse_list_field(item.get("clobTokenIds"))
                if len(outcomes) != 2 or len(clob_ids) != 2:
                    continue

                question = str(item.get("question", "") or "")
                if self.exclude_range_markets and self._is_range_market(question):
                    continue

                yes_token_id, no_token_id = self._map_yes_no_tokens(outcomes, clob_ids)
                if not yes_token_id or not no_token_id:
                    continue

                candidates.append(
                    ArbMarket(
                        id=item.get("conditionId") or item.get("id"),
                        question=question,
                        slug=str(item.get("slug", "") or ""),
                        end_date=end_date,
                        volume_usd=vol,
                        yes_token_id=yes_token_id,
                        no_token_id=no_token_id,
                        time_to_settlement_sec=time_to_settlement
                    )
                )
            except Exception as exc:
                logger.warning("Error processing market item: %s", exc)
                continue

        logger.info("Found %s arb candidates after filtering.", len(candidates))
        return candidates


def _parse_list_field(value: object) -> List[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            import json
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            return []
    return []
