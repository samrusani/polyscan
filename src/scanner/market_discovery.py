import requests
import logging
from typing import List, Optional, Dict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.infra.logger import setup_logger

logger = logging.getLogger("scanner.discovery")

@dataclass
class Market:
    id: str  # This is the market ID (condition ID or similar, used for lookup)
    question: str
    slug: str
    end_date: datetime
    volume_usd: float
    clob_token_ids: List[str]
    outcomes: List[str]
    yes_token_id: Optional[str] = None
    no_token_id: Optional[str] = None
    time_to_settlement_sec: Optional[float] = None
    volatility: Optional[float] = None
    # Metrics to be filled later
    spread: Optional[float] = None
    depth_usd: Optional[float] = None
    recent_trades: Optional[int] = None
    rank_score: Optional[float] = None
    activity_score: Optional[float] = None
    activity_preferred_side: Optional[str] = None
    activity_preferred_token_id: Optional[str] = None
    activity_mid_range: Optional[float] = None
    activity_price_changes: Optional[float] = None
    activity_size_change_hits: Optional[float] = None
    activity_size_change_sum: Optional[float] = None
    activity_samples: Optional[float] = None
    recent_trade_ts: Optional[float] = None
    recent_trade_age_sec: Optional[float] = None

class MarketDiscovery:
    BASE_URL = "https://gamma-api.polymarket.com/events" # Gamma usually returns events which contain markets
    # Actually, let's use /markets endpoint as explored, it returns individual markets
    MARKETS_URL = "https://gamma-api.polymarket.com/markets"

    def __init__(self, config: Dict):
        self.config = config
        self.min_volume = config.get("asset_filter", {}).get("min_volume_usd", 1000)
        self.max_duration_hours = config.get("asset_filter", {}).get("max_duration_hours", 24)
        self.exclude_range_markets = config.get("asset_filter", {}).get("exclude_range_markets", False)

    @staticmethod
    def _is_range_market(question: str) -> bool:
        lowered = question.lower()
        if "between" in lowered or "range" in lowered or "within" in lowered:
            return True
        import re
        return re.search(r"from\s+\$?\d.*\s+to\s+\$?\d", lowered) is not None

    @staticmethod
    def _normalize_outcome_name(outcome: object) -> str:
        if isinstance(outcome, dict):
            name = outcome.get("name") or outcome.get("outcome") or outcome.get("value")
        else:
            name = outcome
        return str(name).strip().lower()

    def _map_yes_no_tokens(self, outcomes: List[object], clob_ids: List[str]) -> tuple[Optional[str], Optional[str]]:
        if not outcomes or not clob_ids or len(outcomes) != len(clob_ids):
            return None, None

        yes_token_id = None
        no_token_id = None

        for idx, outcome in enumerate(outcomes):
            name = self._normalize_outcome_name(outcome)
            if name == "yes":
                yes_token_id = clob_ids[idx]
            elif name == "no":
                no_token_id = clob_ids[idx]

        return yes_token_id, no_token_id
    
    def fetch_markets(self) -> List[Market]:
        logger.info("Fetching markets from Gamma API...")
        
        # We want active markets. 
        # Pagination might be needed if we want full scan, but for "short duration" 
        # we might want to sort by end date? Gamma doesn't support rich sorting in all params.
        # We'll fetch a batch of active markets. 
        # To get enough candidates, we might need a higher limit or pagination.
        # For this MVP, we fetch top 100-500 active markets by volume or default sort.
        
        now = datetime.now(timezone.utc)
        # Calculate max end date based on config
        max_end = now + timedelta(hours=self.max_duration_hours)
        
        params = {
            "active": "true",
            "closed": "false",
            "limit": 500, # Fetch a good chunk
            "order": "volume", # descending volume usually
            "ascending": "false",
            "end_date_max": max_end.isoformat().replace("+00:00", "Z")
        }
        
        try:
            resp = requests.get(self.MARKETS_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            return []

        candidates = []
        now = datetime.now(timezone.utc)
        
        for item in data:
            try:
                # Basic validation
                if not item.get("active"): 
                    # logger.info(f"Dropped {item.get('id')}: Not active")
                    continue
                if item.get("closed"): 
                    # logger.info(f"Dropped {item.get('id')}: Closed")
                    continue
                
                # Check volume
                vol = float(item.get("volume", 0) or 0)
                if vol < self.min_volume:
                    # logger.info(f"Dropped {item.get('id')}: Low volume {vol}")
                    continue

                # Check duration
                end_date_str = item.get("endDate")
                if not end_date_str:
                    continue
                
                # Parse ISO date (handle Z)
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                
                # Duration check: time until settlement
                time_to_settlement = (end_date - now).total_seconds()
                hours_to_settlement = time_to_settlement / 3600.0
                
                if hours_to_settlement < 0:
                    # logger.info(f"Dropped {item.get('id')}: Elapsed")
                    continue # Already elapsed?
                if hours_to_settlement > self.max_duration_hours:
                    logger.info(f"Dropped {item.get('id')}: Duration {hours_to_settlement} > {self.max_duration_hours}")
                    continue
                
                # Binary check: 2 outcomes primarily?
                # Polymarket markets usually have 'outcomes' array
                outcomes = json_outcomes = item.get("outcomes")
                if not isinstance(outcomes, list):
                    # Try parsing if string
                    import json
                    try:
                        outcomes = json.loads(json_outcomes)
                    except:
                        outcomes = []
                
                # We target binary YES/NO
                if len(outcomes) != 2:
                    logger.info(f"Dropped {item.get('id')}: Outcomes {len(outcomes)}")
                    continue
                
                # Get CLOB Token IDs
                clob_ids = item.get("clobTokenIds")
                if isinstance(clob_ids, str):
                    try:
                        import json
                        clob_ids = json.loads(clob_ids)
                    except:
                        clob_ids = []

                if not clob_ids or len(clob_ids) != 2:
                    logger.info(f"Dropped {item.get('id')}: CLOB IDs {clob_ids}")
                    continue

                yes_token_id, no_token_id = self._map_yes_no_tokens(outcomes, clob_ids)
                if not yes_token_id or not no_token_id:
                    logger.info(f"Dropped {item.get('id')}: Unable to map YES/NO tokens")
                    continue

                question = item.get("question", "Unknown")
                if self.exclude_range_markets and self._is_range_market(str(question)):
                    logger.info(f"Dropped {item.get('id')}: Range-style question")
                    continue
                
                market = Market(
                    id=item.get("conditionId") or item.get("id"), # prefer conditionID for uniqueness or just ID
                    question=question,
                    slug=item.get("slug", ""),
                    end_date=end_date,
                    volume_usd=vol,
                    clob_token_ids=clob_ids,
                    outcomes=outcomes,
                    yes_token_id=yes_token_id,
                    no_token_id=no_token_id,
                    time_to_settlement_sec=time_to_settlement
                )
                candidates.append(market)
                
            except Exception as e:
                logger.warning(f"Error processing market item: {e}")
                continue
                
        logger.info(f"Found {len(candidates)} eligible markets after filtering.")
        return candidates
