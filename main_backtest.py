import argparse
import csv
import json
import os
from typing import List, Dict, Any

from src.infra.config import load_config
from src.backtest.runner import load_ticks, run_backtest, run_backtest_multi, infer_token_ids
from src.backtest.sweep import load_sweep, run_sweep


def _write_records(path: str, records):
    if path.lower().endswith(".csv"):
        _write_csv(path, records)
        return
    with open(path, "w") as f:
        f.write(json.dumps(records, indent=2))


def _write_csv(path: str, records):
    if not records:
        with open(path, "w") as f:
            f.write("")
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser(description="Run a simple strategy backtest.")
    parser.add_argument("--data", required=True, help="Path to backtest JSON ticks.")
    parser.add_argument("--token-id", help="Token ID to evaluate.")
    parser.add_argument("--tokens", help="Comma-separated token IDs for multi-token backtest.")
    parser.add_argument("--infer-tokens", action="store_true", help="Infer token IDs from backtest data.")
    parser.add_argument("--trades-out", help="Optional path to write trade log JSON.")
    parser.add_argument("--trades-csv", help="Optional path to write trade log CSV.")
    parser.add_argument("--equity-out", help="Optional path to write equity curve JSON/CSV.")
    parser.add_argument("--sweep", help="Path to JSON sweep grid.")
    parser.add_argument("--sweep-out", help="Path to write sweep results JSON/CSV.")
    parser.add_argument("--max-runs", type=int, default=None, help="Optional cap on sweep runs.")
    args = parser.parse_args()

    config = load_config()
    ticks = load_ticks(args.data)

    token_ids = _resolve_tokens(args, ticks)
    if args.sweep:
        sweep = load_sweep(args.sweep)
        results = run_sweep(config._data, ticks, token_ids, sweep, max_runs=args.max_runs)
        out_path = args.sweep_out or "backtest_sweep.csv"
        _write_records(out_path, results)
        _print_sweep_summary(results)
        return

    if len(token_ids) == 1:
        result = run_backtest(config, token_ids[0], ticks)
    else:
        result = run_backtest_multi(config, token_ids, ticks)

    print("Backtest Summary")
    print(f"Ticks: {result.total_ticks}")
    print(f"BUY_YES: {result.buy_yes}")
    print(f"BUY_NO: {result.buy_no}")
    print(f"NEUTRAL: {result.neutral}")
    print(f"Avg Edge: {result.avg_edge:.4f}")
    print(f"Trades: {result.total_trades}")
    print(f"Win Rate: {result.win_rate * 100:.1f}%")
    print(f"Total PnL: {result.total_pnl:.2f}")
    print(f"Avg PnL/Trade: {result.avg_pnl_per_trade:.2f}")
    print(f"Fees Paid: {result.fees_paid:.2f}")

    if args.trades_out:
        with open(args.trades_out, "w") as f:
            json_trades = [t.__dict__ for t in result.trades]
            f.write(json.dumps(json_trades, indent=2))
    if args.trades_csv:
        _write_csv(args.trades_csv, [t.__dict__ for t in result.trades])
    if args.equity_out:
        _write_records(args.equity_out, result.equity_curve)


def _resolve_tokens(args, ticks) -> List[str]:
    if args.tokens:
        token_ids = [t.strip() for t in args.tokens.split(",") if t.strip()]
    elif args.token_id:
        token_ids = [args.token_id]
    elif args.infer_tokens:
        token_ids = infer_token_ids(ticks)
    else:
        token_ids = []
    if not token_ids:
        raise SystemExit("Provide --token-id, --tokens, or --infer-tokens.")
    return token_ids


def _print_sweep_summary(results: List[Dict[str, Any]]) -> None:
    if not results:
        print("Sweep produced no results.")
        return
    ranked = sorted(results, key=lambda r: r.get("total_pnl", 0), reverse=True)
    top = ranked[:5]
    print("Top Sweep Results (by total_pnl)")
    for row in top:
        print(
            f"run={row.get('run_id')} pnl={row.get('total_pnl'):.2f} "
            f"trades={row.get('total_trades')} win={row.get('win_rate') * 100:.1f}% "
            f"avg_edge={row.get('avg_edge'):.4f}"
        )


if __name__ == "__main__":
    main()
