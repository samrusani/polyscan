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
- Active scanner pipeline: ranked candidates -> orderbook activity probe -> active watchlist (`data/active_watchlist.json`).
- Up/down scanner pipeline: Gamma API -> up/down + yes/no threshold filter -> spot price model -> fair-value watchlist (`data/updown_watchlist.json`).
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
3a. Run active market scanner:
   `python main_active_scanner.py`
   - Uses orderbook activity probing to select the most active markets.
   - Defaults to writing `data/watchlist.json` for direct bot use.
3b. Run up/down scanner:
   `python main_updown_scanner.py`
   - Uses spot price returns to estimate fair value for up/down and YES/NO threshold markets.
   - Outputs `data/updown_watchlist.json` with model probabilities and edges.
   - If it returns empty, lower `updown_scanner.min_edge` or increase `updown_scanner.fetch_limit`.
3c. Run arbitrage scanner:
   `python main_arb_scanner.py`
   - Looks for YES+NO best-ask sums below $1 minus fees.
   - Outputs `data/arb_watchlist.json` with edge estimates.
   - Includes a `near_arb` list with the lowest sum-of-asks when no true arb exists.
   - Appends a JSONL time-series log (`arb_near_arb_log.jsonl`) of the lowest sums.
4. Run bot (paper mode default):
   `python main_bot.py`
5. Dashboard:
   `streamlit run dashboard.py`
   - The “Up/Down” tab reads `data/updown_watchlist.json` for model edges and links questions to the market page.
   - Default paths resolve relative to the repo, so you can run the dashboard from another directory.
   - The “Arb” tab shows near-arb snapshots and a time-series of best sum-of-asks.
6. Backtest (offline):
   `python main_backtest.py --data backtest_sample.json --token-id tokenA --trades-out backtest_trades.json --trades-csv backtest_trades.csv --equity-out backtest_equity.csv`
6a. Record live ticks:
   `python scripts/record_ticks.py --watchlist data/watchlist.json --duration-sec 300 --out backtest_ticks.json`
   - If WS handshake timeouts occur, try `--ws-open-timeout 30`, lower `--max-markets`, or pass headers:
     `python scripts/record_ticks.py --watchlist data/watchlist.json --max-markets 5 --ws-open-timeout 60 --ws-origin https://polymarket.com --ws-header "User-Agent: Mozilla/5.0" --out backtest_ticks.json`
   - HTTP fallback (no websocket): `python scripts/record_ticks.py --watchlist data/watchlist.json --max-markets 5 --transport http --out backtest_ticks.json`
   - Probe for active tokens first: `python scripts/record_ticks.py --watchlist data/watchlist.json --max-markets 20 --probe-trades --probe-lookback 100 --out backtest_ticks.json`
   - Orderbook-activity probe (when trades are sparse): `python scripts/record_ticks.py --watchlist data/watchlist.json --max-markets 50 --probe-orderbook --probe-ob-min-move 0.003 --probe-ob-min-changes 1 --probe-ob-samples 5 --transport http --out backtest_ticks.json`
     - Prints an activity report (mid-range + book changes). Use `--probe-report-top` to limit output.
6b. Backtest recorded ticks:
   `python main_backtest.py --data backtest_ticks.json --infer-tokens --equity-out backtest_equity.csv`
7. Backtest (multi-token):
   `python main_backtest.py --data backtest_sample.json --tokens tokenA,tokenB --equity-out backtest_equity.csv`
   - Use `--infer-tokens` to auto-detect token IDs from the tick file.
   - Offline backtests do not require the live websocket dependency.
8. Backtest sweep:
   `python main_backtest.py --data backtest_sample.json --token-id tokenA --sweep backtest_sweep.example.json --sweep-out backtest_sweep.csv`
9. Analyze account trades (public endpoints):
   `python scripts/analyze_account_trades.py --user Account88888 --output data/account_trades_account88888.json --summary-out data/account_trades_summary.json`
   - If no trades return, pass `--endpoint`, `--param`, `--header`, and use `--debug` for status codes.
   - Use `--raw-out` to save the unparsed payload for inspection.
   - For activity endpoints with offsets: `--endpoint https://data-api.polymarket.com/activity --param user=0x... --limit 25 --offset-param offset --offset-step 25`.
   - Use `--trade-types TRADE,FILL` to filter activity types when a `type` field is present.
   - Use `--probe-endpoints` to quickly see which candidate endpoints return data.
   - Deep scan (polling): `python scripts/analyze_account_trades.py --user 0x... --endpoint https://data-api.polymarket.com/activity --limit 25 --offset-param offset --offset-step 25 --deep-scan --scan-iterations 120 --scan-interval-sec 60 --scan-out data/account_activity_scan.jsonl`
   - Activity endpoints also compute win rate by settled markets using `REDEEM` entries.
9. Plot equity curve:
   `python scripts/plot_backtest.py --equity-csv backtest_equity.csv --out backtest_equity.png`
10. (Optional) Render interactive equity HTML:
   `python scripts/plot_backtest.py --equity-csv backtest_equity.csv --html-out backtest_equity.html`

## Configuration
- `config/config.json`
  - `asset_filter`: market discovery filters
  - `asset_filter.exclude_range_markets`: drop "between/within" range markets during discovery.
- `scanner`: ranking and selection filters (weights, recent trades, volatility, time-to-settlement)
  - `max_spread`: maximum allowable bid/ask spread (defaults to 0.10 for tradable books).
  - `min_depth_near_mid`: minimum USD depth around mid (defaults to 200).
  - `volatility_close_window_sec`: ensure volatility score floor for near-settlement markets.
  - `volatility_close_floor`: minimum volatility score applied when inside the close window.
  - `recent_trade_max_age_sec`: filter markets that haven't traded recently.
  - `near_settlement_window_sec`: window for extra scoring boost close to settlement.
  - `near_settlement_score_boost`: additive score for near-settlement markets.
  - `activity_candidate_limit`: number of ranked markets to probe for activity.
  - `activity_top_n`: number of active markets to keep after probing.
  - `activity_sample_count`: samples per market during the activity probe (default 3).
  - `activity_sample_interval_sec`: seconds between activity probe samples (default 1).
  - `activity_min_mid_range`: minimum mid-range required to pass the probe.
  - `activity_min_book_changes`: minimum top-of-book changes required to pass (default 0).
  - `activity_price_weight`: weight on price changes for activity score.
  - `activity_size_weight`: weight on size changes for activity score.
  - `activity_max_spread`: drop activity-selected markets with spreads above this threshold.
  - `activity_output_path`: output path for active watchlist (defaults to `data/watchlist.json`).
  - `activity_probe_no_tokens`: include NO tokens during activity probing and pick the most active side.
  - `activity_bypass_rank_filters`: skip rank filters and probe discovery markets directly.
  - `activity_enrich_orderbooks`: fetch spread/depth metrics for the active list after probing.
  - `strategy`: signal and quote parameters (tick size, aggression, taker mode)
  - `risk`: loss limits, inventory caps, and per-market throttle
  - `execution`: order sizing and slippage settings
  - `price_feed`: spot price provider selection (binance/coinbase) and lookback window.
  - `updown_scanner`: asset symbols (BTC/ETH/SOL/XRP), volume/duration filters, min-edge threshold, output path, plus YES/NO threshold mapping.
  - Defaults now allow up to 30-day settlement windows for SOL/XRP.
  - `arb_scanner`: filters and fee buffers for YES/NO sum-of-asks arbitrage (defaults scan broader volume/limit).
  - `arb_scanner.near_arb_limit`: number of closest sum-of-asks markets to include in the report.
  - `arb_scanner.near_arb_log_path`: optional JSONL log path for near-arb snapshots.
  - `arb_scanner.near_arb_log_top_n`: number of near-arb entries to log per run.
  - `arb_scanner.min_ask_size`: minimum ask size required to include a market.
  - `arb_scanner.min_ask_notional`: minimum ask notional required per side.
  - Defaults use zero fee buffer/min edge for discovery; tighten before trading.
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
- `backtest.epsilon_override`: optional epsilon override for backtests (does not affect live).
- `backtest.min_edge_override`: optional min-edge override for backtests (does not affect live).
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
- `data/active_watchlist.json`: output from active market scanner
- `data/updown_watchlist.json`: output from up/down fair value scanner
- `data/arb_watchlist.json`: output from arbitrage scanner
- `data/arb_near_arb_log.jsonl`: time-series log of near-arb snapshots
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
- Release notes: `docs/RELEASE_NOTES.md`
