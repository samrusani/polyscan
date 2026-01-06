import argparse
import asyncio
import json
import os
import signal
import sys
import time
from datetime import datetime
from typing import Deque, Dict, Iterable, List, Optional, Tuple
from collections import deque

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from src.bot.data_feed import DataFeed
try:
    from py_clob_client.client import ClobClient
except ImportError:
    ClobClient = None


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


def _parse_headers(raw_headers: List[str]) -> List[tuple[str, str]]:
    headers: List[tuple[str, str]] = []
    for raw in raw_headers:
        if ":" not in raw:
            raise SystemExit("Invalid --ws-header format. Use 'Name: Value'.")
        name, value = raw.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            raise SystemExit("Invalid --ws-header name. Use 'Name: Value'.")
        headers.append((name, value))
    return headers


def _normalize_book_levels(levels: Iterable[object]) -> List[Dict[str, float]]:
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


def _fetch_trades(client: object, token_id: str, limit: int) -> List[object]:
    trades = None
    if hasattr(client, "get_trades"):
        try:
            trades = client.get_trades(token_id=token_id, limit=limit)
        except TypeError:
            try:
                trades = client.get_trades(token_id, limit)
            except Exception:
                trades = None
        except Exception:
            trades = None
    if trades is None:
        return []
    if isinstance(trades, dict):
        trades = trades.get("data") or trades.get("trades") or []
    if not isinstance(trades, list):
        return []
    return trades


def _probe_trade_activity(token_ids: List[str], min_trades: int, lookback: int) -> List[str]:
    if ClobClient is None:
        raise RuntimeError("py-clob-client is required for trade probing.")
    client = ClobClient("https://clob.polymarket.com")
    active: List[str] = []
    for token_id in token_ids:
        trades = _fetch_trades(client, token_id, lookback)
        if len(trades) >= min_trades:
            active.append(token_id)
    return active


def _probe_orderbook_activity(
    token_ids: List[str],
    min_move: float,
    samples: int,
    interval_sec: float
) -> List[str]:
    if ClobClient is None:
        raise RuntimeError("py-clob-client is required for orderbook probing.")
    client = ClobClient("https://clob.polymarket.com")
    mids: Dict[str, List[float]] = {token_id: [] for token_id in token_ids}
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
            mid = (bids[0]["price"] + asks[0]["price"]) / 2
            mids[token_id].append(mid)
        if interval_sec > 0:
            time.sleep(interval_sec)
    active: List[str] = []
    for token_id, values in mids.items():
        if len(values) < 2:
            continue
        if max(values) - min(values) >= min_move:
            active.append(token_id)
    return active


def _trade_key(trade: object) -> Tuple[str, str]:
    if isinstance(trade, dict):
        trade_id = trade.get("id") or trade.get("trade_id") or trade.get("tradeId")
        if trade_id is not None:
            return ("id", str(trade_id))
        price = trade.get("price")
        size = trade.get("size")
        side = trade.get("side")
        ts = trade.get("timestamp") or trade.get("createdAt") or trade.get("created_at")
    else:
        trade_id = getattr(trade, "id", None) or getattr(trade, "trade_id", None)
        if trade_id is not None:
            return ("id", str(trade_id))
        price = getattr(trade, "price", None)
        size = getattr(trade, "size", None)
        side = getattr(trade, "side", None)
        ts = getattr(trade, "timestamp", None) or getattr(trade, "createdAt", None)
    return ("fp", f"{price}|{size}|{side}|{ts}")


def _trade_timestamp(trade: object) -> str:
    if isinstance(trade, dict):
        ts = trade.get("timestamp") or trade.get("createdAt") or trade.get("created_at")
    else:
        ts = getattr(trade, "timestamp", None) or getattr(trade, "createdAt", None)
    if isinstance(ts, str) and ts:
        return ts
    return datetime.utcnow().isoformat()


async def record_ticks(
    token_ids: List[str],
    out_path: str,
    duration_sec: int,
    snapshot_sec: float,
    max_ticks: int | None,
    include_trades: bool,
    connect_kwargs: Optional[Dict[str, object]],
    backoff_sec: float
) -> None:
    feed = DataFeed(token_ids, connect_kwargs=connect_kwargs, backoff_sec=backoff_sec)
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
    if not ticks:
        print("Warning: no ticks captured. Check WS connectivity or reduce markets.")


async def record_ticks_http(
    token_ids: List[str],
    out_path: str,
    duration_sec: int,
    snapshot_sec: float,
    max_ticks: int | None,
    include_trades: bool,
    trades_limit: int
) -> None:
    if ClobClient is None:
        raise RuntimeError("py-clob-client is required for HTTP tick recording.")
    client = ClobClient("https://clob.polymarket.com")
    ticks: List[Dict] = []
    stop_event = asyncio.Event()
    seen_trades: Dict[str, Deque[Tuple[str, str]]] = {
        token_id: deque(maxlen=2000) for token_id in token_ids
    }

    def _stop() -> None:
        if not stop_event.is_set():
            stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    start_ts = time.time()
    try:
        while not stop_event.is_set():
            now = time.time()
            if duration_sec and now - start_ts >= duration_sec:
                break

            tick = {"timestamp": datetime.utcnow().isoformat()}
            orderbooks = []
            for token_id in token_ids:
                try:
                    ob = await asyncio.to_thread(client.get_order_book, token_id)
                except Exception:
                    continue
                bids = _normalize_book_levels(getattr(ob, "bids", []) or [])
                asks = _normalize_book_levels(getattr(ob, "asks", []) or [])
                if not bids or not asks:
                    continue
                orderbooks.append({
                    "token_id": token_id,
                    "book": {"bids": bids, "asks": asks}
                })
            if orderbooks:
                tick["orderbooks"] = orderbooks

            if include_trades:
                trades_out = []
                for token_id in token_ids:
                    trades = None
                    if hasattr(client, "get_trades"):
                        try:
                            trades = await asyncio.to_thread(
                                client.get_trades,
                                token_id=token_id,
                                limit=trades_limit
                            )
                        except TypeError:
                            try:
                                trades = await asyncio.to_thread(client.get_trades, token_id, trades_limit)
                            except Exception:
                                trades = None
                        except Exception:
                            trades = None
                    if trades is None:
                        continue
                    if isinstance(trades, dict):
                        trades = trades.get("data") or trades.get("trades") or []
                    if not isinstance(trades, list):
                        continue
                    for trade in trades:
                        key = _trade_key(trade)
                        if key in seen_trades[token_id]:
                            continue
                        seen_trades[token_id].append(key)
                        if isinstance(trade, dict):
                            price = trade.get("price")
                            size = trade.get("size")
                            side = trade.get("side")
                        else:
                            price = getattr(trade, "price", None)
                            size = getattr(trade, "size", None)
                            side = getattr(trade, "side", None)
                        trades_out.append({
                            "token_id": token_id,
                            "price": float(price) if price is not None else 0.0,
                            "size": float(size) if size is not None else 0.0,
                            "side": side,
                            "timestamp": _trade_timestamp(trade)
                        })
                if trades_out:
                    tick["trades"] = trades_out

            if "orderbooks" in tick or "trades" in tick:
                ticks.append(tick)

            if max_ticks and len(ticks) >= max_ticks:
                break

            await asyncio.sleep(snapshot_sec)
    finally:
        pass

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(json.dumps(ticks, indent=2))
    if not ticks:
        print("Warning: no ticks captured. Check HTTP connectivity or reduce markets.")


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
    parser.add_argument("--ws-open-timeout", type=float, default=None, help="Websocket open timeout seconds.")
    parser.add_argument("--ws-backoff-sec", type=float, default=5.0, help="Reconnect backoff seconds.")
    parser.add_argument("--ws-origin", default=None, help="Origin header override for websocket handshake.")
    parser.add_argument(
        "--ws-header",
        action="append",
        default=[],
        help="Extra websocket header (repeatable, format 'Name: Value')."
    )
    parser.add_argument(
        "--transport",
        choices=["ws", "http"],
        default="ws",
        help="Transport for tick capture: ws (default) or http."
    )
    parser.add_argument(
        "--http-trades-limit",
        type=int,
        default=50,
        help="Trade limit per token per HTTP poll."
    )
    parser.add_argument(
        "--probe-trades",
        action="store_true",
        help="Filter tokens to those with recent trades before recording."
    )
    parser.add_argument(
        "--probe-min-trades",
        type=int,
        default=1,
        help="Minimum recent trades required to keep a token."
    )
    parser.add_argument(
        "--probe-lookback",
        type=int,
        default=50,
        help="Trade lookback size for probing."
    )
    parser.add_argument(
        "--probe-orderbook",
        action="store_true",
        help="Filter tokens to those with recent mid-price movement."
    )
    parser.add_argument(
        "--probe-ob-min-move",
        type=float,
        default=0.005,
        help="Minimum mid-price range to keep a token during orderbook probe."
    )
    parser.add_argument(
        "--probe-ob-samples",
        type=int,
        default=3,
        help="Number of orderbook samples per token for probing."
    )
    parser.add_argument(
        "--probe-ob-interval-sec",
        type=float,
        default=2.0,
        help="Seconds between orderbook probe samples."
    )
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

    if args.probe_trades:
        token_ids = _probe_trade_activity(token_ids, args.probe_min_trades, args.probe_lookback)
        if not token_ids:
            raise SystemExit("Trade probe found no active tokens. Lower --probe-min-trades or increase --probe-lookback.")
        print(f"Probe (trades): {len(token_ids)} tokens with trades.")
    if args.probe_orderbook:
        token_ids = _probe_orderbook_activity(
            token_ids,
            args.probe_ob_min_move,
            args.probe_ob_samples,
            args.probe_ob_interval_sec
        )
        if not token_ids:
            raise SystemExit("Orderbook probe found no moving tokens. Lower --probe-ob-min-move or increase samples.")
        print(f"Probe (orderbook): {len(token_ids)} tokens with mid moves.")

    if args.transport == "http":
        asyncio.run(
            record_ticks_http(
                token_ids=token_ids,
                out_path=args.out,
                duration_sec=args.duration_sec,
                snapshot_sec=args.snapshot_sec,
                max_ticks=args.max_ticks,
                include_trades=not args.no_trades,
                trades_limit=args.http_trades_limit
            )
        )
    else:
        connect_kwargs = {}
        if args.ws_open_timeout is not None:
            connect_kwargs["open_timeout"] = args.ws_open_timeout
        if args.ws_origin:
            connect_kwargs["origin"] = args.ws_origin
        if args.ws_header:
            connect_kwargs["extra_headers"] = _parse_headers(args.ws_header)
        asyncio.run(
            record_ticks(
                token_ids=token_ids,
                out_path=args.out,
                duration_sec=args.duration_sec,
                snapshot_sec=args.snapshot_sec,
                max_ticks=args.max_ticks,
                include_trades=not args.no_trades,
                connect_kwargs=connect_kwargs or None,
                backoff_sec=args.ws_backoff_sec
            )
        )


if __name__ == "__main__":
    main()
