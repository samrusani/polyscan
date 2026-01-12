import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

logger = logging.getLogger("scanner.updown")

UP_OUTCOME_NAMES = {"up", "higher", "above", "increase", "upward"}
DOWN_OUTCOME_NAMES = {"down", "lower", "below", "decrease", "downward"}

ASSET_ALIASES = {
    "BTC": ["btc", "bitcoin"],
    "ETH": ["eth", "ethereum"],
    "SOL": ["sol", "solana"],
    "XRP": ["xrp", "ripple"]
}


@dataclass
class UpDownMarket:
    id: str
    question: str
    slug: str
    end_date: datetime
    volume_usd: float
    clob_token_ids: List[str]
    outcomes: List[str]
    up_token_id: Optional[str] = None
    down_token_id: Optional[str] = None
    yes_token_id: Optional[str] = None
    no_token_id: Optional[str] = None
    asset_symbol: Optional[str] = None
    direction_hint: Optional[str] = None
    target_price: Optional[float] = None
    is_range_market: Optional[bool] = None
    time_to_settlement_sec: Optional[float] = None
    spot_price: Optional[float] = None
    model_prob_up: Optional[float] = None
    model_prob_down: Optional[float] = None
    model_return_mean: Optional[float] = None
    model_return_stdev: Optional[float] = None
    model_return_samples: Optional[int] = None
    best_bid_up: Optional[float] = None
    best_ask_up: Optional[float] = None
    best_bid_down: Optional[float] = None
    best_ask_down: Optional[float] = None
    mid_up: Optional[float] = None
    mid_down: Optional[float] = None
    spread_up: Optional[float] = None
    spread_down: Optional[float] = None
    edge_up: Optional[float] = None
    edge_down: Optional[float] = None
    edge_best: Optional[float] = None
    recommended_side: Optional[str] = None


class UpDownMarketDiscovery:
    MARKETS_URL = "https://gamma-api.polymarket.com/markets"

    def __init__(self, config: Dict[str, object]):
        self.config = config
        self.min_volume = float(config.get("min_volume_usd", 1000))
        self.max_duration_hours = float(config.get("max_duration_hours", 168))
        self.fetch_limit = int(config.get("fetch_limit", 500))
        symbols = config.get("asset_symbols", ["BTC", "ETH"])
        self.asset_symbols = [str(sym).upper() for sym in symbols]

    def fetch_markets(self) -> List[UpDownMarket]:
        logger.info("Fetching up/down markets from Gamma API...")
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

        candidates: List[UpDownMarket] = []
        now = datetime.now(timezone.utc)

        for item in data:
            try:
                if not item.get("active") or item.get("closed"):
                    continue

                volume = float(item.get("volume", 0) or 0)
                if volume < self.min_volume:
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
                slug = str(item.get("slug", "") or "")
                asset_symbol = _detect_asset_symbol(f"{question} {slug}", self.asset_symbols)
                if not asset_symbol:
                    continue

                up_token_id, down_token_id = _map_up_down_tokens(outcomes, clob_ids)
                yes_token_id, no_token_id = _map_yes_no_tokens(outcomes, clob_ids)
                if not (up_token_id and down_token_id) and not (yes_token_id and no_token_id):
                    continue

                direction_hint, target_price, is_range_market = _infer_direction(question)

                candidates.append(
                    UpDownMarket(
                        id=item.get("conditionId") or item.get("id"),
                        question=question,
                        slug=slug,
                        end_date=end_date,
                        volume_usd=volume,
                        clob_token_ids=clob_ids,
                        outcomes=outcomes,
                        up_token_id=up_token_id,
                        down_token_id=down_token_id,
                        yes_token_id=yes_token_id,
                        no_token_id=no_token_id,
                        asset_symbol=asset_symbol,
                        direction_hint=direction_hint,
                        target_price=target_price,
                        is_range_market=is_range_market,
                        time_to_settlement_sec=time_to_settlement
                    )
                )
            except Exception as exc:
                logger.warning("Error processing up/down market: %s", exc)
                continue

        logger.info("Found %s up/down markets after filtering.", len(candidates))
        return candidates


def _normalize_outcome_name(outcome: object) -> str:
    if isinstance(outcome, dict):
        name = outcome.get("name") or outcome.get("outcome") or outcome.get("value")
    else:
        name = outcome
    return str(name).strip().lower()


def _map_up_down_tokens(outcomes: List[object], clob_ids: List[str]) -> tuple[Optional[str], Optional[str]]:
    if not outcomes or not clob_ids or len(outcomes) != len(clob_ids):
        return None, None

    up_token_id = None
    down_token_id = None

    for idx, outcome in enumerate(outcomes):
        name = _normalize_outcome_name(outcome)
        if name in UP_OUTCOME_NAMES:
            up_token_id = clob_ids[idx]
        elif name in DOWN_OUTCOME_NAMES:
            down_token_id = clob_ids[idx]

    return up_token_id, down_token_id


def _map_yes_no_tokens(outcomes: List[object], clob_ids: List[str]) -> tuple[Optional[str], Optional[str]]:
    if not outcomes or not clob_ids or len(outcomes) != len(clob_ids):
        return None, None

    yes_token_id = None
    no_token_id = None

    for idx, outcome in enumerate(outcomes):
        name = _normalize_outcome_name(outcome)
        if name == "yes":
            yes_token_id = clob_ids[idx]
        elif name == "no":
            no_token_id = clob_ids[idx]

    return yes_token_id, no_token_id


def _detect_asset_symbol(text: str, allowed_symbols: List[str]) -> Optional[str]:
    lowered = text.lower()
    for symbol in allowed_symbols:
        aliases = ASSET_ALIASES.get(symbol, [symbol.lower()])
        for alias in aliases:
            if alias in lowered:
                return symbol
    return None


def _infer_direction(text: str) -> tuple[Optional[str], Optional[float], Optional[bool]]:
    lowered = text.lower()

    range_pattern = re.compile(r"(between\s+\$?\d|from\s+\$?\d.*\s+to\s+\$?\d)")
    if "between" in lowered or "range" in lowered or range_pattern.search(lowered):
        return None, _extract_target_price(lowered), True

    down_keywords = [
        "below",
        "lower",
        "under",
        "less than",
        "dip",
        "fall",
        "drop",
        "at most"
    ]
    up_keywords = [
        "above",
        "higher",
        "over",
        "greater than",
        "at least",
        "exceed"
    ]

    for key in down_keywords:
        if key in lowered:
            return "DOWN", _extract_target_price(lowered), False

    for key in up_keywords:
        if key in lowered:
            return "UP", _extract_target_price(lowered), False

    return None, _extract_target_price(lowered), False


def _extract_target_price(text: str) -> Optional[float]:
    dollar_match = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)", text)
    if dollar_match:
        return _to_float(dollar_match.group(1))

    keyword_match = re.search(
        r"(reach|above|below|over|under|less than|more than|at least|at most|greater than|higher than|lower than|dip to|fall to|drop to|touch)\s*\$?([0-9]+(?:\.[0-9]+)?)",
        text
    )
    if keyword_match:
        return _to_float(keyword_match.group(2))

    return None


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
