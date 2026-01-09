import argparse
import json
import os
import time
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

import requests


CANDIDATE_ENDPOINTS = [
    ("https://clob.polymarket.com/trades", {"user": "{user}", "limit": "{limit}"}),
    ("https://clob.polymarket.com/trades", {"maker": "{user}", "limit": "{limit}"}),
    ("https://clob.polymarket.com/trades", {"taker": "{user}", "limit": "{limit}"}),
    ("https://clob.polymarket.com/v1/trades", {"user": "{user}", "limit": "{limit}"}),
    ("https://clob.polymarket.com/v1/trades", {"maker": "{user}", "limit": "{limit}"}),
    ("https://clob.polymarket.com/v1/trades", {"taker": "{user}", "limit": "{limit}"}),
    ("https://clob.polymarket.com/v2/trades", {"user": "{user}", "limit": "{limit}"}),
    ("https://clob.polymarket.com/v2/trades", {"maker": "{user}", "limit": "{limit}"}),
    ("https://clob.polymarket.com/v2/trades", {"taker": "{user}", "limit": "{limit}"}),
    ("https://polymarket.com/api/trades", {"user": "{user}", "limit": "{limit}"}),
    ("https://polymarket.com/api/v0/trades", {"user": "{user}", "limit": "{limit}"}),
    ("https://data-api.polymarket.com/activity", {"user": "{user}", "limit": "{limit}", "offset": "0"})
]


def _parse_params(raw_params: List[str]) -> Dict[str, str]:
    params: Dict[str, str] = {}
    for raw in raw_params:
        if "=" not in raw:
            raise SystemExit("Invalid --param format. Use key=value.")
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SystemExit("Invalid --param key. Use key=value.")
        params[key] = value
    return params


def _parse_headers(raw_headers: List[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for raw in raw_headers:
        if ":" not in raw:
            raise SystemExit("Invalid --header format. Use 'Name: Value'.")
        name, value = raw.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            raise SystemExit("Invalid --header name. Use 'Name: Value'.")
        headers[name] = value
    return headers


def _extract_trades(payload: object) -> List[dict]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in ("data", "trades", "results", "items", "activity"):
            value = payload.get(key)
            if isinstance(value, list):
                return [p for p in value if isinstance(p, dict)]
            if isinstance(value, dict):
                nested = value.get("trades") or value.get("data") or value.get("results")
                if isinstance(nested, list):
                    return [p for p in nested if isinstance(p, dict)]
    return []


def _load_jsonl(path: str) -> List[dict]:
    items: List[dict] = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                items.append(item)
    return items


def _activity_key(item: dict) -> str:
    tx = item.get("transactionHash") or item.get("txHash") or item.get("hash")
    if tx:
        return f"tx:{tx}"
    parts = [
        item.get("type"),
        item.get("timestamp"),
        item.get("asset"),
        item.get("side"),
        item.get("size"),
        item.get("price"),
        item.get("conditionId"),
        item.get("slug")
    ]
    return "fp:" + "|".join(str(p) for p in parts if p is not None)


def _load_seen_keys(path: str) -> set[str]:
    seen: set[str] = set()
    if not os.path.exists(path):
        return seen
    for item in _load_jsonl(path):
        seen.add(_activity_key(item))
    return seen


def _extract_cursor(payload: object) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    for key in ("next_cursor", "nextCursor", "next", "cursor", "next_page", "nextPage"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _parse_timestamp(raw: object) -> Optional[datetime]:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_side(raw: object) -> str:
    if not raw:
        return "UNKNOWN"
    value = str(raw).strip().upper()
    if value in ("BUY", "SELL"):
        return value
    if value in ("B", "S"):
        return "BUY" if value == "B" else "SELL"
    if value in ("LONG", "SHORT"):
        return "BUY" if value == "LONG" else "SELL"
    return value


def _unwrap_trade(raw: dict) -> dict:
    for key in ("trade", "fill", "details", "event"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            return nested
    return raw


def _normalize_trade(raw: dict, allowed_types: Optional[set[str]] = None) -> Optional[dict]:
    if allowed_types:
        raw_type = raw.get("type")
        if raw_type and str(raw_type).upper() not in allowed_types:
            return None
    raw = _unwrap_trade(raw)
    if allowed_types:
        raw_type = raw.get("type")
        if raw_type and str(raw_type).upper() not in allowed_types:
            return None
    price = raw.get("price") or raw.get("trade_price") or raw.get("fill_price")
    size = raw.get("size") or raw.get("quantity") or raw.get("amount") or raw.get("shares")
    token_id = (
        raw.get("token_id")
        or raw.get("asset_id")
        or raw.get("clob_token_id")
        or raw.get("tokenId")
        or raw.get("asset")
        or raw.get("market_id")
        or raw.get("marketId")
    )
    side = raw.get("side") or raw.get("action") or raw.get("type") or raw.get("order_side")
    timestamp = raw.get("timestamp") or raw.get("created_at") or raw.get("createdAt") or raw.get("time")

    try:
        price = float(price)
        size = float(size)
    except (TypeError, ValueError):
        return None

    return {
        "token_id": token_id,
        "price": price,
        "size": size,
        "side": _normalize_side(side),
        "timestamp": timestamp
    }


def _fetch_trades_from_endpoint(
    url: str,
    params: Dict[str, str],
    limit_param: str,
    cursor_param: Optional[str],
    page_param: Optional[str],
    offset_param: Optional[str],
    offset_step: int,
    max_pages: int,
    timeout_sec: int,
    headers: Dict[str, str],
    debug: bool
) -> List[dict]:
    trades: List[dict] = []
    cursor_value = None
    offset_value = 0
    for page in range(max_pages):
        request_params = dict(params)
        if limit_param and "limit" in params:
            request_params[limit_param] = request_params.pop("limit")
        if cursor_param and cursor_value:
            request_params[cursor_param] = cursor_value
        if page_param:
            request_params[page_param] = str(page + 1)
        if offset_param:
            request_params[offset_param] = str(offset_value)

        resp = requests.get(url, params=request_params, headers=headers or None, timeout=timeout_sec)
        if debug:
            print(f"GET {resp.url} -> {resp.status_code}")
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        payload = resp.json()
        batch = _extract_trades(payload)
        if not batch:
            break
        trades.extend(batch)
        cursor_value = _extract_cursor(payload)
        if cursor_param and cursor_value:
            continue
        if offset_param:
            limit_value = None
            if limit_param and limit_param in request_params:
                limit_value = request_params.get(limit_param)
            else:
                limit_value = request_params.get("limit")
            try:
                limit_value = int(limit_value) if limit_value is not None else None
            except (TypeError, ValueError):
                limit_value = None
            step = offset_step or limit_value or 0
            if step <= 0:
                break
            offset_value += step
        if not page_param:
            break
    return trades


def _fetch_trades(
    user: str,
    limit: int,
    max_pages: int,
    timeout_sec: int,
    endpoint: Optional[str],
    base_url: Optional[str],
    limit_param: str,
    cursor_param: Optional[str],
    page_param: Optional[str],
    offset_param: Optional[str],
    offset_step: int,
    extra_params: Dict[str, str],
    headers: Dict[str, str],
    debug: bool
) -> Tuple[List[dict], str]:
    if endpoint:
        if endpoint.startswith("http"):
            url = endpoint
        elif base_url:
            url = base_url.rstrip("/") + "/" + endpoint.lstrip("/")
        else:
            url = "https://clob.polymarket.com/" + endpoint.lstrip("/")
        params = {"user": user, "limit": str(limit)}
        params.update(extra_params)
        trades = _fetch_trades_from_endpoint(
            url,
            params,
            limit_param,
            cursor_param,
            page_param,
            offset_param,
            offset_step,
            max_pages,
            timeout_sec,
            headers,
            debug
        )
        return trades, url

    last_error = None
    errors: List[str] = []
    for url, template in CANDIDATE_ENDPOINTS:
        params = {}
        for key, value in template.items():
            if value == "{user}":
                params[key] = user
            elif value == "{limit}":
                params[key] = str(limit)
            else:
                params[key] = value
        params.update(extra_params)
        try:
            trades = _fetch_trades_from_endpoint(
                url,
                params,
                limit_param,
                cursor_param,
                page_param,
                offset_param,
                offset_step,
                max_pages,
                timeout_sec,
                headers,
                debug
            )
            if trades:
                return trades, url
        except Exception as exc:
            last_error = exc
            errors.append(f"{url}: {exc}")
            continue
    if debug and errors:
        print("Endpoint errors:")
        for err in errors:
            print(f"  {err}")
    raise SystemExit(f"Failed to fetch trades from candidate endpoints: {last_error}")


def _probe_candidate_endpoints(
    user: str,
    limit: int,
    max_pages: int,
    timeout_sec: int,
    limit_param: str,
    cursor_param: Optional[str],
    page_param: Optional[str],
    offset_param: Optional[str],
    offset_step: int,
    extra_params: Dict[str, str],
    headers: Dict[str, str]
) -> None:
    print("Endpoint probe:")
    for url, template in CANDIDATE_ENDPOINTS:
        params = {}
        for key, value in template.items():
            if value == "{user}":
                params[key] = user
            elif value == "{limit}":
                params[key] = str(limit)
            else:
                params[key] = value
        params.update(extra_params)
        try:
            trades = _fetch_trades_from_endpoint(
                url,
                params,
                limit_param,
                cursor_param,
                page_param,
                offset_param,
                offset_step,
                max_pages,
                timeout_sec,
                headers,
                True
            )
            print(f"  {url} -> {len(trades)} items")
        except Exception as exc:
            print(f"  {url} -> error: {exc}")


def _deep_scan_activity(
    user: str,
    endpoint: str,
    limit: int,
    max_pages: int,
    timeout_sec: int,
    limit_param: str,
    cursor_param: Optional[str],
    page_param: Optional[str],
    offset_param: Optional[str],
    offset_step: int,
    params: Dict[str, str],
    headers: Dict[str, str],
    iterations: int,
    interval_sec: int,
    out_path: str,
    debug: bool
) -> None:
    base_params = {"user": user, "limit": str(limit)}
    base_params.update(params)
    seen = _load_seen_keys(out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    for idx in range(iterations):
        batch = _fetch_trades_from_endpoint(
            endpoint,
            base_params,
            limit_param,
            cursor_param,
            page_param,
            offset_param,
            offset_step,
            max_pages,
            timeout_sec,
            headers,
            debug
        )
        new_count = 0
        with open(out_path, "a") as f:
            for item in batch:
                if not isinstance(item, dict):
                    continue
                key = _activity_key(item)
                if key in seen:
                    continue
                seen.add(key)
                f.write(json.dumps(item) + "\n")
                new_count += 1
        print(
            f"Scan {idx + 1}/{iterations}: fetched {len(batch)} items, "
            f"new {new_count}, total {len(seen)}"
        )
        if idx + 1 < iterations and interval_sec > 0:
            time.sleep(interval_sec)


def _sort_trades(trades: List[dict]) -> List[dict]:
    parsed = []
    for trade in trades:
        ts = _parse_timestamp(trade.get("timestamp"))
        parsed.append((ts, trade))
    if all(ts is None for ts, _ in parsed):
        return trades
    return [trade for ts, trade in sorted(parsed, key=lambda item: item[0] or datetime.min)]


def _compute_pnl(trades: Iterable[dict]) -> dict:
    positions: Dict[str, Dict[str, float]] = {}
    realized_pnl: Dict[str, float] = {}
    wins: Dict[str, int] = {}
    losses: Dict[str, int] = {}
    trade_counts: Dict[str, int] = {}
    closes = 0

    for trade in trades:
        token_id = trade.get("token_id") or "unknown"
        side = trade.get("side")
        price = float(trade.get("price", 0.0))
        size = float(trade.get("size", 0.0))
        if size <= 0:
            continue

        state = positions.setdefault(token_id, {"qty": 0.0, "avg_price": 0.0})
        qty = state["qty"]
        avg_price = state["avg_price"]

        trade_counts[token_id] = trade_counts.get(token_id, 0) + 1

        if side == "BUY":
            if qty >= 0:
                new_qty = qty + size
                state["avg_price"] = ((avg_price * qty) + (price * size)) / new_qty
                state["qty"] = new_qty
            else:
                close_size = min(size, abs(qty))
                pnl = (avg_price - price) * close_size
                realized_pnl[token_id] = realized_pnl.get(token_id, 0.0) + pnl
                closes += 1
                if pnl > 0:
                    wins[token_id] = wins.get(token_id, 0) + 1
                elif pnl < 0:
                    losses[token_id] = losses.get(token_id, 0) + 1
                remaining = size - close_size
                state["qty"] = qty + close_size
                if remaining > 0:
                    state["avg_price"] = price
                    state["qty"] = remaining
        elif side == "SELL":
            if qty <= 0:
                new_qty = qty - size
                state["avg_price"] = ((avg_price * abs(qty)) + (price * size)) / abs(new_qty)
                state["qty"] = new_qty
            else:
                close_size = min(size, qty)
                pnl = (price - avg_price) * close_size
                realized_pnl[token_id] = realized_pnl.get(token_id, 0.0) + pnl
                closes += 1
                if pnl > 0:
                    wins[token_id] = wins.get(token_id, 0) + 1
                elif pnl < 0:
                    losses[token_id] = losses.get(token_id, 0) + 1
                remaining = size - close_size
                state["qty"] = qty - close_size
                if remaining > 0:
                    state["avg_price"] = price
                    state["qty"] = -remaining
        else:
            continue

    total_realized = sum(realized_pnl.values())
    total_wins = sum(wins.values())
    total_losses = sum(losses.values())
    win_rate = total_wins / (total_wins + total_losses) if (total_wins + total_losses) else 0.0
    avg_pnl = total_realized / closes if closes else 0.0

    notes = []
    if closes == 0:
        notes.append("No closes detected; realized PnL is zero. Check for SELL/close trades or settlement data.")
    return {
        "realized_pnl_by_token": realized_pnl,
        "trade_counts_by_token": trade_counts,
        "wins_by_token": wins,
        "losses_by_token": losses,
        "open_positions": positions,
        "total_realized_pnl": total_realized,
        "win_rate": win_rate,
        "avg_pnl_per_close": avg_pnl,
        "total_closes": closes,
        "notes": notes
    }


def _compute_activity_market_pnl(raw_items: Iterable[object]) -> dict:
    markets: Dict[str, Dict[str, object]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        condition_id = item.get("conditionId") or item.get("condition_id")
        if not condition_id:
            continue
        entry = markets.setdefault(condition_id, {
            "condition_id": condition_id,
            "title": item.get("title"),
            "slug": item.get("slug"),
            "trade_count": 0,
            "buy_count": 0,
            "sell_count": 0,
            "cost_usdc": 0.0,
            "redeem_usdc": 0.0
        })
        entry["title"] = entry["title"] or item.get("title")
        entry["slug"] = entry["slug"] or item.get("slug")
        item_type = str(item.get("type") or "").upper()
        usdc_val = item.get("usdcSize")
        if usdc_val is None:
            try:
                usdc_val = float(item.get("price")) * float(item.get("size"))
            except (TypeError, ValueError):
                usdc_val = None
        try:
            usdc_val = float(usdc_val) if usdc_val is not None else None
        except (TypeError, ValueError):
            usdc_val = None

        if item_type == "TRADE":
            entry["trade_count"] += 1
            side = str(item.get("side") or "").upper()
            if side == "SELL":
                entry["sell_count"] += 1
                if usdc_val is not None:
                    entry["cost_usdc"] -= usdc_val
            else:
                entry["buy_count"] += 1
                if usdc_val is not None:
                    entry["cost_usdc"] += usdc_val
        elif item_type in ("REDEEM", "SETTLE", "PAYOUT"):
            if usdc_val is not None:
                entry["redeem_usdc"] += usdc_val

    market_rows = []
    wins = 0
    losses = 0
    for entry in markets.values():
        redeem = float(entry.get("redeem_usdc") or 0.0)
        cost = float(entry.get("cost_usdc") or 0.0)
        net = redeem - cost
        settled = redeem > 0
        if settled:
            if net > 0:
                wins += 1
            elif net < 0:
                losses += 1
        entry["net_pnl_usdc"] = net if settled else None
        entry["settled"] = settled
        market_rows.append(entry)

    market_rows.sort(key=lambda row: (row.get("net_pnl_usdc") or 0.0), reverse=True)
    total_settled = wins + losses
    win_rate = wins / total_settled if total_settled else 0.0
    return {
        "markets": market_rows,
        "settled_count": total_settled,
        "win_rate": win_rate,
        "wins": wins,
        "losses": losses
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and analyze Polymarket account trades.")
    parser.add_argument("--user", help="Account handle or address.")
    parser.add_argument("--input", help="Path to raw trades JSON (skip fetch).")
    parser.add_argument("--output", help="Path to write raw trades JSON.")
    parser.add_argument("--raw-out", help="Path to write unparsed trade payload JSON.")
    parser.add_argument("--summary-out", help="Path to write summary JSON.")
    parser.add_argument("--endpoint", help="Override endpoint URL or path.")
    parser.add_argument("--base-url", help="Base URL if endpoint is a path.")
    parser.add_argument("--limit", type=int, default=500, help="Trades per request.")
    parser.add_argument("--max-pages", type=int, default=5, help="Max pages to fetch.")
    parser.add_argument("--limit-param", default="limit", help="Query parameter for limit.")
    parser.add_argument("--cursor-param", default=None, help="Cursor parameter name.")
    parser.add_argument("--page-param", default=None, help="Page parameter name.")
    parser.add_argument("--offset-param", default=None, help="Offset parameter name.")
    parser.add_argument("--offset-step", type=int, default=0, help="Offset increment per page (default=limit).")
    parser.add_argument("--param", action="append", default=[], help="Extra query param key=value.")
    parser.add_argument("--header", action="append", default=[], help="Extra header 'Name: Value'.")
    parser.add_argument("--timeout", type=int, default=15, help="Request timeout in seconds.")
    parser.add_argument("--no-sort", action="store_true", help="Skip timestamp sorting.")
    parser.add_argument("--debug", action="store_true", help="Print request URLs and errors.")
    parser.add_argument(
        "--trade-types",
        default="TRADE,FILL",
        help="Comma-separated activity types to keep when a 'type' field is present."
    )
    parser.add_argument(
        "--probe-endpoints",
        action="store_true",
        help="Print candidate endpoint status codes and result sizes, then exit."
    )
    parser.add_argument(
        "--deep-scan",
        action="store_true",
        help="Poll an endpoint repeatedly and append unique activity items to a JSONL file."
    )
    parser.add_argument("--scan-iterations", type=int, default=60, help="Number of scan iterations.")
    parser.add_argument("--scan-interval-sec", type=int, default=60, help="Seconds between scan iterations.")
    parser.add_argument("--scan-out", help="JSONL output path for deep scans.")
    args = parser.parse_args()

    trades_raw: List[dict] = []
    source = "input"

    if args.input:
        if args.input.endswith(".jsonl"):
            trades_raw = _load_jsonl(args.input)
        else:
            with open(args.input, "r") as f:
                payload = json.load(f)
            trades_raw = _extract_trades(payload)
    elif args.deep_scan:
        if not args.user:
            raise SystemExit("Deep scan requires --user.")
        if not args.endpoint:
            raise SystemExit("Deep scan requires --endpoint.")
        params = _parse_params(args.param)
        headers = _parse_headers(args.header)
        out_path = args.scan_out or os.path.join(
            "data", f"account_activity_scan_{args.user.lstrip('@')}.jsonl"
        )
        _deep_scan_activity(
            user=args.user.lstrip("@"),
            endpoint=args.endpoint,
            limit=args.limit,
            max_pages=args.max_pages,
            timeout_sec=args.timeout,
            limit_param=args.limit_param,
            cursor_param=args.cursor_param,
            page_param=args.page_param,
            offset_param=args.offset_param,
            offset_step=args.offset_step,
            params=params,
            headers=headers,
            iterations=args.scan_iterations,
            interval_sec=args.scan_interval_sec,
            out_path=out_path,
            debug=args.debug
        )
        return
    else:
        if not args.user:
            raise SystemExit("Provide --user or --input.")
        params = _parse_params(args.param)
        headers = _parse_headers(args.header)
        if args.probe_endpoints:
            _probe_candidate_endpoints(
                user=args.user.lstrip("@"),
                limit=args.limit,
                max_pages=args.max_pages,
                timeout_sec=args.timeout,
                limit_param=args.limit_param,
                cursor_param=args.cursor_param,
                page_param=args.page_param,
                offset_param=args.offset_param,
                offset_step=args.offset_step,
                extra_params=params,
                headers=headers
            )
            return
        trades_raw, source = _fetch_trades(
            user=args.user.lstrip("@"),
            limit=args.limit,
            max_pages=args.max_pages,
            timeout_sec=args.timeout,
            endpoint=args.endpoint,
            base_url=args.base_url,
            limit_param=args.limit_param,
            cursor_param=args.cursor_param,
            page_param=args.page_param,
            offset_param=args.offset_param,
            offset_step=args.offset_step,
            extra_params=params,
            headers=headers,
            debug=args.debug
        )

    if args.raw_out:
        os.makedirs(os.path.dirname(args.raw_out) or ".", exist_ok=True)
        with open(args.raw_out, "w") as f:
            f.write(json.dumps(trades_raw, indent=2))
        print(f"Wrote raw payload to {args.raw_out}")

    if not trades_raw:
        raise SystemExit("No trades returned. Try --endpoint or adjust params.")

    trade_type_set = {t.strip().upper() for t in args.trade_types.split(",") if t.strip()}
    normalized = []
    for trade in trades_raw:
        normalized_trade = _normalize_trade(trade, trade_type_set)
        if normalized_trade:
            normalized.append(normalized_trade)

    if not normalized:
        raise SystemExit("Trades returned but none could be parsed.")

    if not args.no_sort:
        normalized = _sort_trades(normalized)

    summary = _compute_pnl(normalized)
    activity_summary = _compute_activity_market_pnl(trades_raw)
    summary["activity_markets"] = activity_summary
    summary["source"] = source
    summary["total_trades"] = len(normalized)

    print("Trade Summary")
    print(f"Source: {source}")
    print(f"Trades: {summary['total_trades']}")
    print(f"Realized PnL: {summary['total_realized_pnl']:.2f}")
    print(f"Win Rate (by closes): {summary['win_rate'] * 100:.1f}%")
    print(f"Avg PnL/Close: {summary['avg_pnl_per_close']:.4f}")
    if activity_summary["settled_count"]:
        print(
            f"Activity Win Rate (settled markets): {activity_summary['win_rate'] * 100:.1f}% "
            f"({activity_summary['wins']}/{activity_summary['settled_count']})"
        )

    if args.output:
        out_path = args.output
    elif args.user:
        out_path = os.path.join("data", f"account_trades_{args.user.lstrip('@')}.json")
    else:
        out_path = None

    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w") as f:
            f.write(json.dumps(normalized, indent=2))
        print(f"Wrote normalized trades to {out_path}")

    if args.summary_out:
        os.makedirs(os.path.dirname(args.summary_out) or ".", exist_ok=True)
        with open(args.summary_out, "w") as f:
            f.write(json.dumps(summary, indent=2))
        print(f"Wrote summary to {args.summary_out}")


if __name__ == "__main__":
    main()
