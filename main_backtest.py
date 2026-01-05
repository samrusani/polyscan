import argparse
import csv
import json
import os

from src.infra.config import load_config
from src.backtest.runner import load_ticks, run_backtest


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
    parser.add_argument("--token-id", required=True, help="Token ID to evaluate.")
    parser.add_argument("--trades-out", help="Optional path to write trade log JSON.")
    parser.add_argument("--trades-csv", help="Optional path to write trade log CSV.")
    parser.add_argument("--equity-out", help="Optional path to write equity curve JSON/CSV.")
    args = parser.parse_args()

    config = load_config()
    ticks = load_ticks(args.data)
    result = run_backtest(config, args.token_id, ticks)

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

    if args.trades_out:
        with open(args.trades_out, "w") as f:
            json_trades = [t.__dict__ for t in result.trades]
            f.write(json.dumps(json_trades, indent=2))
    if args.trades_csv:
        _write_csv(args.trades_csv, [t.__dict__ for t in result.trades])
    if args.equity_out:
        _write_records(args.equity_out, result.equity_curve)


if __name__ == "__main__":
    main()
