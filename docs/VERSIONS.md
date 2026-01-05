# Versions

All changes are recorded in chronological order. Append new entries to the end.

## 2026-01-04
- v0.1.0 - Baseline import of the Polymarket scanner/bot/dashboard codebase.
- v0.1.1 - Added documentation set (`docs/README.md`, `docs/ROADMAP.md`, `docs/KNOWN_ISSUES.md`, `docs/VERSIONS.md`) and documentation update rule; linked from root README.
- v0.1.2 - Mapped YES/NO tokens in scanner/watchlist, normalized order books, improved paper fills, wired PnL into risk halts, and added `.env.example`.
- v0.1.3 - Replaced deprecated event loop usage with `asyncio.run` and signal-safe shutdown in `main_bot.py`.
- v0.1.4 - Added pytest path bootstrap so tests can import `src` from the project root.
- v0.1.5 - Added tests covering strategy quoting, risk gating, and paper simulation fills.
- v0.1.6 - Added live-mode risk halt tests and a lightweight LiveExecutor mock.
- v0.1.7 - Fixed test import to use local fakes module for live-mode risk tests.
- v0.1.8 - Short-circuited risk handling on daily halt to avoid per-market blocks during global stop.
- v0.1.9 - Updated logger timestamps to use timezone-aware UTC to avoid deprecation warnings.
- v0.2.0 - Enhanced scanner scoring with recent trades, volatility, and time-to-settlement weighting plus config defaults.
- v0.2.1 - Added taker-mode quoting controls, more aggressive config defaults, and market snapshot data in the dashboard.
- v0.2.2 - Normalized quote signals to accumulate the selected token and documented the strategy behavior.
- v0.2.3 - Guarded dashboard open-orders columns when market snapshot fields are missing.
- v0.2.4 - Added edge-gated strategy tuning, signal evaluation stats, dashboard strategy metrics, and strategy tests.
- v0.2.5 - Stabilized taker-mode test spread threshold to avoid float edge cases.
- v0.2.6 - Added live fill polling and reconciliation with new execution config for poll interval.
- v0.2.7 - Cleaned up roadmap placeholder and removed unused import in live executor.
- v0.2.8 - Clarified PnL/risk update comment for live reconciliation flow.
- v0.2.9 - Added fill fingerprint dedupe for live reconciliation without fill IDs.
- v0.3.0 - Added live reconciliation timestamps to state and dashboard for visibility.
- v0.3.1 - Added live open-order caching with periodic refresh and dashboard integration.
- v0.3.2 - Added live order cache refresh indicators to the dashboard and state.
- v0.3.3 - Switched order cache refresh indicator to seconds-ago display.
- v0.3.4 - Added dashboard staleness banners for live reconciliation and order-cache refresh.
