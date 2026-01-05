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
- Dashboard: Streamlit app reading `data/live_state.json` for PnL, positions, orders, market snapshots, and strategy stats.

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

## Configuration
- `config/config.json`
  - `asset_filter`: market discovery filters
  - `scanner`: ranking and selection filters (weights, recent trades, volatility, time-to-settlement)
  - `strategy`: signal and quote parameters (tick size, aggression, taker mode)
  - `risk`: loss limits and inventory caps
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

## Data Artifacts
- `data/watchlist.json`: output from scanner (includes `yes_token_id`/`no_token_id`)
- `data/live_state.json`: runtime state for dashboard
- `data/session_*.csv`: session trade exports
- `logs/bot.jsonl`: structured logs

## Risk Handling
- Daily loss limit halts trading and cancels open orders.
- Per-market loss limit blocks tokens and flattens positions in paper mode.
- Live mode polls recent fills and updates portfolio + risk on each poll.
- Dashboard shows last live poll and fill timestamps for reconciliation health.
- Dashboard shows last order-cache refresh and cache size in live mode.
- Dashboard banners warn when reconciliation or order-cache refresh is stale.

## Reference Docs
- Roadmap: `docs/ROADMAP.md`
- Known issues: `docs/KNOWN_ISSUES.md`
- Version log: `docs/VERSIONS.md`
