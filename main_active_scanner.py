import json
import os
from dataclasses import asdict
from datetime import datetime

from src.infra.config import load_config
from src.infra.logger import setup_logger
from src.scanner.activity_probe import compute_activity_score, probe_orderbook_activity
from src.scanner.market_discovery import MarketDiscovery
from src.scanner.ranking import MarketRanker

logger = setup_logger("active_scanner")


def main() -> None:
    logger.info("Starting Active Market Scanner...")

    config = load_config()
    scanner_cfg = config.scanner

    discovery = MarketDiscovery(config._data)
    markets = discovery.fetch_markets()
    if not markets:
        logger.warning("No markets found matching basic criteria.")
        return

    ranker = MarketRanker(config)
    ranked_markets = ranker.rank_markets(markets)
    if not ranked_markets:
        logger.warning("No markets left after ranking filters.")
        return

    candidate_limit = scanner_cfg.get("activity_candidate_limit", 50)
    candidates = ranked_markets[:candidate_limit] if candidate_limit else ranked_markets
    token_ids = []
    for market in candidates:
        if market.yes_token_id:
            token_ids.append(market.yes_token_id)
        if scanner_cfg.get("activity_probe_no_tokens", False) and market.no_token_id:
            token_ids.append(market.no_token_id)
    if not token_ids:
        logger.warning("No token IDs available for activity probing.")
        return

    min_move = float(scanner_cfg.get("activity_min_mid_range", 0.0))
    min_changes = int(scanner_cfg.get("activity_min_book_changes", 1))
    samples = int(scanner_cfg.get("activity_sample_count", 5))
    interval_sec = float(scanner_cfg.get("activity_sample_interval_sec", 2.0))

    active_tokens, metrics = probe_orderbook_activity(
        token_ids=token_ids,
        min_move=min_move,
        min_changes=min_changes,
        samples=samples,
        interval_sec=interval_sec
    )

    price_weight = float(scanner_cfg.get("activity_price_weight", 0.01))
    size_weight = float(scanner_cfg.get("activity_size_weight", 0.001))

    if not active_tokens:
        logger.warning("Activity probe found no active tokens.")

    active_markets = []
    for market in candidates:
        yes_stats = metrics.get(market.yes_token_id) if market.yes_token_id else None
        no_stats = metrics.get(market.no_token_id) if market.no_token_id else None
        yes_score = compute_activity_score(yes_stats, price_weight, size_weight) if yes_stats else None
        no_score = compute_activity_score(no_stats, price_weight, size_weight) if no_stats else None

        preferred_side = "YES"
        stats = yes_stats
        score = yes_score
        if no_score is not None and (score is None or no_score > score):
            preferred_side = "NO"
            stats = no_stats
            score = no_score

        if not stats:
            continue

        market.activity_preferred_side = preferred_side
        market.activity_preferred_token_id = market.yes_token_id if preferred_side == "YES" else market.no_token_id
        market.activity_mid_range = stats.get("mid_range")
        market.activity_price_changes = stats.get("price_changes")
        market.activity_size_change_hits = stats.get("size_change_hits")
        market.activity_size_change_sum = stats.get("size_change_sum")
        market.activity_samples = stats.get("samples")
        market.activity_score = score

        if market.activity_preferred_token_id in active_tokens:
            active_markets.append(market)

    if not active_markets:
        logger.warning("Activity probe found no active markets.")

    active_markets.sort(
        key=lambda m: (
            m.activity_score or 0.0,
            m.rank_score or 0.0
        ),
        reverse=True
    )
    top_n = scanner_cfg.get("activity_top_n", scanner_cfg.get("top_n", 10))
    active_markets = active_markets[:top_n]

    timestamp = datetime.utcnow().isoformat()
    output_data = {
        "generated_at": timestamp,
        "probe_settings": {
            "candidate_limit": candidate_limit,
            "min_mid_range": min_move,
            "min_book_changes": min_changes,
            "samples": samples,
            "interval_sec": interval_sec,
            "price_weight": price_weight,
            "size_weight": size_weight
        },
        "markets": [asdict(m) for m in active_markets]
    }

    def json_serial(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    data_dir = "data"
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    output_path = scanner_cfg.get("activity_output_path", os.path.join(data_dir, "active_watchlist.json"))
    with open(output_path, "w") as f:
        json.dump(output_data, f, default=json_serial, indent=2)

    logger.info(f"Active watchlist written to {output_path}")


if __name__ == "__main__":
    main()
