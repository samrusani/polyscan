import argparse
import asyncio
import json
import os
import signal
import sys
import time
from datetime import datetime
from typing import Dict, List

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from src.bot.data_feed import DataFeed


def _parse_token_ids(raw: str) -> List[str]:
    return [token.strip() for token in raw.split(",") if token.strip()]


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    ordered = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _load_watchlist_tokens(path: str, include_yes: bool, include_no: bool, max_markets: int | None) -> List[str]:
    with open(path, "r") as f:
        payload = json.load(f)
    markets = payload.get("markets", []) if isinstance(payload, dict) else []
    token_ids: List[str] = []
    for idx, market in enumerate(markets):
        if max_markets is not None and idx >= max_markets:
            break
        if include_yes:
            yes_id = market.get("yes_token_id")
            if yes_id:
                token_ids.append(yes_id)
        if include_no:
            no_id = market.get("no_token_id")
            if no_id:
                token_ids.append(no_id)
    return token_ids


async def record_ticks(
    token_ids: List[str],
    out_path: str,
    duration_sec: int,
    snapshot_sec: float,
    max_ticks: int | None,
    include_trades: bool
) -> None:
    feed = DataFeed(token_ids)
    trade_buffer: Dict[str, List[Dict]] = {token_id: [] for token_id in token_ids}
    ticks: List[Dict] = []
    stop_event = asyncio.Event()

    def _on_event(event: Dict) -> None:
        if event.get("event_type") != "last_trade_price":
            return
        token_id = event.get("asset_id")
        if token_id not in trade_buffer:
            return
        trade = {
            "token_id": token_id,
            "price": float(event.get("price") or 0),
            "size": float(event.get("size") or 0),
            "side": event.get("side"),
            "timestamp": datetime.utcnow().isoformat()
        }
        trade_buffer[token_id].append(trade)

    def _stop() -> None:
        if not stop_event.is_set():
            stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    feed.subscribe(_on_event)
    await feed.start()

    start_ts = time.time()
    try:
        while not stop_event.is_set():
            now = time.time()
            if duration_sec and now - start_ts >= duration_sec:
                break

            tick = {"timestamp": datetime.utcnow().isoformat()}
            orderbooks = []
            for token_id in token_ids:
                ob = feed.get_orderbook(token_id)
                if not ob or not ob.get("bids") or not ob.get("asks"):
                    continue
                orderbooks.append({
                    "token_id": token_id,
                    "book": {"bids": ob["bids"], "asks": ob["asks"]}
                })
            if orderbooks:
                tick["orderbooks"] = orderbooks

            if include_trades:
                trades = []
                for token_id in token_ids:
                    if trade_buffer[token_id]:
                        trades.extend(trade_buffer[token_id])
                        trade_buffer[token_id] = []
                if trades:
                    tick["trades"] = trades

            if "orderbooks" in tick or "trades" in tick:
                ticks.append(tick)

            if max_ticks and len(ticks) >= max_ticks:
                break

            await asyncio.sleep(snapshot_sec)
    finally:
        await feed.stop()

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(json.dumps(ticks, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Record live ticks for backtesting.")
    parser.add_argument("--token-ids", help="Comma-separated token IDs to record.")
    parser.add_argument("--watchlist", help="Path to watchlist.json for token IDs.")
    parser.add_argument("--max-markets", type=int, default=None, help="Limit markets read from watchlist.")
    parser.add_argument("--yes-only", action="store_true", help="Only record YES tokens from watchlist.")
    parser.add_argument("--no-only", action="store_true", help="Only record NO tokens from watchlist.")
    parser.add_argument("--duration-sec", type=int, default=300, help="Duration to record.")
    parser.add_argument("--snapshot-sec", type=float, default=1.0, help="Snapshot interval.")
    parser.add_argument("--max-ticks", type=int, default=None, help="Maximum ticks to record.")
    parser.add_argument("--out", default="backtest_ticks.json", help="Output JSON file.")
    parser.add_argument("--no-trades", action="store_true", help="Skip recording trades.")
    args = parser.parse_args()

    token_ids: List[str] = []
    if args.token_ids:
        token_ids.extend(_parse_token_ids(args.token_ids))
    if args.watchlist:
        include_yes = not args.no_only
        include_no = not args.yes_only
        token_ids.extend(_load_watchlist_tokens(args.watchlist, include_yes, include_no, args.max_markets))

    token_ids = _dedupe(token_ids)
    if not token_ids:
        raise SystemExit("Provide --token-ids and/or --watchlist to select tokens.")

    asyncio.run(
        record_ticks(
            token_ids=token_ids,
            out_path=args.out,
            duration_sec=args.duration_sec,
            snapshot_sec=args.snapshot_sec,
            max_ticks=args.max_ticks,
            include_trades=not args.no_trades
        )
    )


if __name__ == "__main__":
    main()
