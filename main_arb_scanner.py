import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from typing import Optional, Tuple

from py_clob_client.client import ClobClient

from src.infra.config import load_config
from src.infra.logger import setup_logger
from src.scanner.arb_scanner import ArbMarket, ArbMarketDiscovery

logger = setup_logger("arb_scanner")


def _best_bid_ask(client: ClobClient, token_id: str) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    try:
        ob = client.get_order_book(token_id)
    except Exception as exc:
        logger.warning("Orderbook fetch failed for %s: %s", token_id, exc)
        return None, None, None, None

    bids = getattr(ob, "bids", []) or []
    asks = getattr(ob, "asks", []) or []
    if not bids or not asks:
        return None, None, None, None

    def _price_size(level: object) -> Tuple[Optional[float], Optional[float]]:
        if isinstance(level, dict):
            price = level.get("price")
            size = level.get("size")
        else:
            price = getattr(level, "price", None)
            size = getattr(level, "size", None)
        try:
            price_val = float(price)
            size_val = float(size)
        except (TypeError, ValueError):
            return None, None
        return price_val, size_val

    best_bid, best_bid_size = _price_size(bids[0])
    best_ask, best_ask_size = _price_size(asks[0])
    return best_bid, best_bid_size, best_ask, best_ask_size


def main() -> None:
    logger.info("Starting Arb Scanner...")

    config = load_config()
    arb_cfg = config.arb_scanner

    discovery = ArbMarketDiscovery(arb_cfg)
    markets = discovery.fetch_markets()
    if not markets:
        logger.warning("No markets found for arb scan.")
        return

    client = ClobClient("https://clob.polymarket.com")
    fee_buffer = float(arb_cfg.get("fee_buffer", 0.0))
    min_edge = float(arb_cfg.get("min_edge", 0.0))
    min_ask_size = arb_cfg.get("min_ask_size")
    min_ask_notional = arb_cfg.get("min_ask_notional")

    opportunities: list[ArbMarket] = []
    near_candidates: list[ArbMarket] = []
    for market in markets:
        bid_yes, bid_yes_size, ask_yes, ask_yes_size = _best_bid_ask(client, market.yes_token_id)
        bid_no, bid_no_size, ask_no, ask_no_size = _best_bid_ask(client, market.no_token_id)

        market.best_bid_yes = bid_yes
        market.best_ask_yes = ask_yes
        market.best_bid_yes_size = bid_yes_size
        market.best_ask_yes_size = ask_yes_size
        market.best_bid_no = bid_no
        market.best_ask_no = ask_no
        market.best_bid_no_size = bid_no_size
        market.best_ask_no_size = ask_no_size

        if ask_yes is None or ask_no is None:
            continue
        if min_ask_size is not None:
            if ask_yes_size is None or ask_no_size is None:
                continue
            if ask_yes_size < float(min_ask_size) or ask_no_size < float(min_ask_size):
                continue
        if min_ask_notional is not None:
            if ask_yes_size is None or ask_no_size is None:
                continue
            if ask_yes * ask_yes_size < float(min_ask_notional):
                continue
            if ask_no * ask_no_size < float(min_ask_notional):
                continue

        market.sum_asks = ask_yes + ask_no
        market.sum_bids = (bid_yes or 0.0) + (bid_no or 0.0)
        market.edge_buy_both = (1.0 - fee_buffer) - market.sum_asks

        if market.edge_buy_both is not None:
            near_candidates.append(market)
        if market.edge_buy_both is not None and market.edge_buy_both >= min_edge:
            opportunities.append(market)

    opportunities.sort(key=lambda m: m.edge_buy_both or 0.0, reverse=True)
    max_markets = int(arb_cfg.get("max_markets", 50))
    if max_markets:
        opportunities = opportunities[:max_markets]

    timestamp = datetime.utcnow().isoformat()
    near_candidates.sort(key=lambda m: m.sum_asks or 999.0)
    near_limit = int(arb_cfg.get("near_arb_limit", 20))
    if near_limit:
        near_candidates = near_candidates[:near_limit]

    output_data = {
        "generated_at": timestamp,
        "scanner_settings": {
            "min_volume_usd": arb_cfg.get("min_volume_usd"),
            "max_duration_hours": arb_cfg.get("max_duration_hours"),
            "fee_buffer": fee_buffer,
            "min_edge": min_edge,
            "max_markets": max_markets,
            "near_arb_limit": near_limit,
            "min_ask_size": min_ask_size,
            "min_ask_notional": min_ask_notional
        },
        "markets": [asdict(m) for m in opportunities],
        "near_arb": [asdict(m) for m in near_candidates]
    }

    data_dir = "data"
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    output_path = arb_cfg.get("output_path", os.path.join(data_dir, "arb_watchlist.json"))
    with open(output_path, "w") as f:
        json.dump(output_data, f, default=_json_serial, indent=2)

    log_path = arb_cfg.get("near_arb_log_path", "")
    if log_path:
        top_n = int(arb_cfg.get("near_arb_log_top_n", near_limit))
        _append_near_arb_log(log_path, near_candidates, timestamp, top_n)

    logger.info("Arb watchlist written to %s", output_path)


def _json_serial(obj: object):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def _append_near_arb_log(path: str, markets: list[ArbMarket], timestamp: str, top_n: int) -> None:
    if not markets or top_n <= 0:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    snapshot = []
    for market in markets[:top_n]:
        snapshot.append(
            {
                "id": market.id,
                "question": market.question,
                "slug": market.slug,
                "end_date": market.end_date.isoformat(),
                "volume_usd": market.volume_usd,
                "sum_asks": market.sum_asks,
                "edge_buy_both": market.edge_buy_both,
                "best_ask_yes": market.best_ask_yes,
                "best_ask_no": market.best_ask_no,
                "best_ask_yes_size": market.best_ask_yes_size,
                "best_ask_no_size": market.best_ask_no_size
            }
        )
    record = {
        "timestamp": timestamp,
        "near_arb_top": snapshot
    }
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    main()
