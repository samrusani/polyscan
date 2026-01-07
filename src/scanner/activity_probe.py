import time
from typing import Dict, List, Tuple

try:
    from py_clob_client.client import ClobClient
except ImportError:
    ClobClient = None


def _normalize_book_levels(levels: List[object]) -> List[Dict[str, float]]:
    normalized: List[Dict[str, float]] = []
    for level in levels:
        if isinstance(level, dict):
            price = level.get("price")
            size = level.get("size")
        else:
            price = getattr(level, "price", None)
            size = getattr(level, "size", None)
        try:
            price_f = float(price)
            size_f = float(size)
        except (TypeError, ValueError):
            continue
        if size_f <= 0:
            continue
        normalized.append({"price": price_f, "size": size_f})
    return normalized


def compute_activity_score(stats: Dict[str, float], price_weight: float, size_weight: float) -> float:
    samples = max(int(stats.get("samples", 0)) - 1, 1)
    mid_range = float(stats.get("mid_range", 0.0))
    price_rate = float(stats.get("price_changes", 0.0)) / samples
    size_rate = float(stats.get("size_change_sum", 0.0)) / samples
    return mid_range + (price_rate * price_weight) + (size_rate * size_weight)


def probe_orderbook_activity(
    token_ids: List[str],
    min_move: float,
    min_changes: int,
    samples: int,
    interval_sec: float
) -> tuple[List[str], Dict[str, Dict[str, float]]]:
    if ClobClient is None:
        raise RuntimeError("py-clob-client is required for orderbook probing.")
    client = ClobClient("https://clob.polymarket.com")
    mids: Dict[str, List[float]] = {token_id: [] for token_id in token_ids}
    snapshots: Dict[str, List[Tuple[float, float, float, float]]] = {
        token_id: [] for token_id in token_ids
    }

    for _ in range(max(samples, 1)):
        for token_id in token_ids:
            try:
                ob = client.get_order_book(token_id)
            except Exception:
                continue
            bids = _normalize_book_levels(getattr(ob, "bids", []) or [])
            asks = _normalize_book_levels(getattr(ob, "asks", []) or [])
            if not bids or not asks:
                continue
            best_bid = bids[0]
            best_ask = asks[0]
            mid = (best_bid["price"] + best_ask["price"]) / 2
            mids[token_id].append(mid)
            snapshots[token_id].append(
                (best_bid["price"], best_bid["size"], best_ask["price"], best_ask["size"])
            )
        if interval_sec > 0:
            time.sleep(interval_sec)

    active: List[str] = []
    metrics: Dict[str, Dict[str, float]] = {}
    for token_id, values in mids.items():
        if len(values) < 2 or len(snapshots[token_id]) < 2:
            continue
        mid_range = max(values) - min(values)
        price_changes = 0
        size_hits = 0
        size_sum = 0.0
        sample_list = snapshots[token_id]
        for idx in range(1, len(sample_list)):
            prev_bid_p, prev_bid_s, prev_ask_p, prev_ask_s = sample_list[idx - 1]
            bid_p, bid_s, ask_p, ask_s = sample_list[idx]
            if bid_p != prev_bid_p:
                price_changes += 1
            if ask_p != prev_ask_p:
                price_changes += 1
            size_delta = abs(bid_s - prev_bid_s) + abs(ask_s - prev_ask_s)
            if size_delta > 0:
                size_hits += 1
                size_sum += size_delta
        change_hits = price_changes + size_hits
        metrics[token_id] = {
            "mid_range": mid_range,
            "price_changes": float(price_changes),
            "size_change_hits": float(size_hits),
            "size_change_sum": size_sum,
            "samples": float(len(values))
        }
        if mid_range >= min_move or change_hits >= min_changes:
            active.append(token_id)

    return active, metrics
