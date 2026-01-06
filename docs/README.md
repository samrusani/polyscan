# Documentation

This folder is the handoff-ready source of truth for the project.

## Documentation Update Rule (Hard)
- Every change to code, configuration, or behavior must update the docs.
- Always add a new entry to `docs/VERSIONS.md` for each change.
- Update `docs/ROADMAP.md` and `docs/KNOWN_ISSUES.md` when scope or risks change.
- If a change is not documented, it is not done.

## Project Summary
Polyscan is a Polymarket scanner and market-making bot for short-duration binary markets. It discovers active markets, ranks them by liquidity and spread, and trades with a biased quoting strategy in paper or live mode.

## System Overview
- Scanner pipeline: Gamma API -> filter -> CLOB order book metrics -> ranked watchlist (`data/watchlist.json`) with explicit `yes_token_id`/`no_token_id`.
- Bot pipeline: watchlist -> websocket feed -> strategy -> risk checks -> executor -> portfolio -> live state export (`data/live_state.json`).
- Dashboard: Streamlit app reading `data/live_state.json` for PnL, positions, orders, market snapshots, strategy stats, and backtest equity.
- Backtest: offline runner replays tick data to evaluate strategy signals.

## Runbook
1. Install dependencies:
   `pip install -r requirements.txt`
2. Copy config:
   `cp config/config.example.json config/config.json`
3. Run scanner:
   `python main_scanner.py`
   - Re-run the scanner after code updates to refresh watchlist schema.
4. Run bot (paper mode default):
   `python main_bot.py`
5. Dashboard:
   `streamlit run dashboard.py`
6. Backtest (offline):
   `python main_backtest.py --data backtest_sample.json --token-id tokenA --trades-out backtest_trades.json --trades-csv backtest_trades.csv --equity-out backtest_equity.csv`
6a. Record live ticks:
   `python scripts/record_ticks.py --watchlist data/watchlist.json --duration-sec 300 --out backtest_ticks.json`
6b. Backtest recorded ticks:
   `python main_backtest.py --data backtest_ticks.json --infer-tokens --equity-out backtest_equity.csv`
7. Backtest (multi-token):
   `python main_backtest.py --data backtest_sample.json --tokens tokenA,tokenB --equity-out backtest_equity.csv`
   - Use `--infer-tokens` to auto-detect token IDs from the tick file.
   - Offline backtests do not require the live websocket dependency.
8. Backtest sweep:
   `python main_backtest.py --data backtest_sample.json --token-id tokenA --sweep backtest_sweep.example.json --sweep-out backtest_sweep.csv`
9. Plot equity curve:
   `python scripts/plot_backtest.py --equity-csv backtest_equity.csv --out backtest_equity.png`
10. (Optional) Render interactive equity HTML:
   `python scripts/plot_backtest.py --equity-csv backtest_equity.csv --html-out backtest_equity.html`

## Configuration
- `config/config.json`
  - `asset_filter`: market discovery filters
  - `scanner`: ranking and selection filters (weights, recent trades, volatility, time-to-settlement)
  - `strategy`: signal and quote parameters (tick size, aggression, taker mode)
  - `risk`: loss limits, inventory caps, and per-market throttle
  - `execution`: order sizing and slippage settings
- Live trading requires environment variables (see `.env.example` and root README).

## Strategy Controls
- `tick_size`: price increment for quote adjustments.
- `buy_aggression_ticks`: how far to improve bids when accumulating.
- `sell_offset`: how far above best ask to place passive sells.
- `taker_mode`: when true, crosses the spread to take liquidity if spread <= `taker_max_spread`.
- `taker_min_edge`: minimum edge required before taker-mode crosses.
- `min_edge_to_trade`: minimum edge required to place orders at all.
- `evaluation_window_sec`: delay before evaluating a signal outcome.
- `min_edge_to_evaluate`: minimum edge required to include a signal in evaluation stats.
- Signals select the target token; quotes are always biased to accumulate that token.

## Execution Controls
- `live_fill_poll_interval_sec`: how often to poll live fills for reconciliation.
- `live_order_cache_enabled`: keep a local cache of live open orders.
- `live_order_cache_refresh_sec`: periodic refresh interval for the live order cache.
- `order_retry_attempts`: retry count for live order API calls.
- `order_retry_backoff_sec`: base backoff seconds between retries.

## Backtest Controls
- `backtest.position_size`: size used for simulated positions.
- `backtest.price_mode`: `mid` (default) or `conservative` (bid/ask).
- `backtest.close_at_end`: close any open position on the final tick.
- `backtest.fee_bps`: per-fill fee in basis points.
- `backtest.slippage_bps`: per-fill slippage in basis points.
- `backtest.slippage_ticks`: per-fill slippage in ticks.
- `backtest.trade_history_limit`: cap on stored trades for fair-value windows.
- `backtest.strategy_mode`: `live` (trade-based fair value) or `mid` (mid-price window).
- `backtest.mid_fair_value_window`: window size for mid-price fair value when using `strategy_mode=mid`.
- Backtests apply `strategy.min_edge_to_trade` gating.
Multi-token data can include:
- `orderbooks`: list of `{token_id, book}` entries per tick.
- `trades`: list of `{token_id, price, size}` entries per tick.
Recorded tick files use `orderbooks` + `trades` at a snapshot interval.

## Parameter Sweeps
- Sweep files are JSON objects mapping dot-path config keys to lists.
- Example: `backtest_sweep.example.json`.
- Use `--max-runs` to cap large grids.

## Alert Controls
- `alerts.enable`: turn alerts on/off.
- `alerts.mode`: `log` (local logs) or `webhook` (HTTP POST).
- `alerts.webhook_url`: destination for alert payloads.
- `alerts.min_interval_sec`: minimum time between alerts.
- `alerts.pnl_alert_threshold_usd`: total PnL threshold for alerts.
- `alerts.stale_recon_multiplier`: multiplier on poll interval before stale alert.

## Data Artifacts
- `data/watchlist.json`: output from scanner (includes `yes_token_id`/`no_token_id`)
- `data/live_state.json`: runtime state for dashboard
- `data/session_*.csv`: session trade exports
- `logs/bot.jsonl`: structured logs
- `backtest_sample.json`: sample tick data format for offline backtests
- `backtest_trades.json`: optional trade log output from `main_backtest.py`
- `backtest_trades.csv`: optional trade log CSV output from `main_backtest.py`
- `backtest_equity.csv`: optional equity curve output from `main_backtest.py`
- `backtest_equity.png`: optional equity curve image from `scripts/plot_backtest.py`
- `backtest_equity.html`: optional equity curve HTML from `scripts/plot_backtest.py`
- `backtest_sweep.csv`: optional parameter sweep results from `main_backtest.py`
- `backtest_sweep.example.json`: example sweep grid input
- `backtest_ticks.json`: recorded live ticks for backtesting
Note: backtest output artifacts are gitignored by default; keep them local.

## Risk Handling
- Daily loss limit halts trading and cancels open orders.
- Per-market loss limit blocks tokens and flattens positions in paper mode.
- Live mode polls recent fills and updates portfolio + risk on each poll.
- Dashboard shows last live poll and fill timestamps for reconciliation health.
- Dashboard shows last order-cache refresh and cache size in live mode.
- Dashboard banners warn when reconciliation or order-cache refresh is stale.
- Per-market order throttling limits how frequently orders can be placed for a token.

## Alerts
- Optional alerts for risk breaches, PnL thresholds, and stale reconciliation.

## Reference Docs
- Roadmap: `docs/ROADMAP.md`
- Known issues: `docs/KNOWN_ISSUES.md`
- Version log: `docs/VERSIONS.md`
