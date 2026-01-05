import argparse
import csv

import plotly.express as px


def load_equity(path: str):
    rows = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "equity" not in row:
                continue
            row["equity"] = float(row["equity"])
            rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description="Plot backtest equity curve.")
    parser.add_argument("--equity-csv", required=True, help="Path to equity curve CSV.")
    parser.add_argument("--out", help="Output image path (png).")
    parser.add_argument("--html-out", help="Output HTML path.")
    args = parser.parse_args()

    if not args.out and not args.html_out:
        raise SystemExit("Provide --out and/or --html-out for output.")

    rows = load_equity(args.equity_csv)
    if not rows:
        raise SystemExit("No equity data found in CSV.")

    fig = px.line(rows, x="timestamp", y="equity", title="Backtest Equity Curve")
    if args.out:
        fig.write_image(args.out)
    if args.html_out:
        fig.write_html(args.html_out)


if __name__ == "__main__":
    main()
