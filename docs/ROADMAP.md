# Roadmap

## Near Term
- TBD

## Mid Term
- Expand scanner metrics (recent trades, volatility, time-to-settlement weighting).
- Track open orders locally in live mode for fewer API calls.
- Add Slack-formatted webhook alert payloads.

## Long Term
- Robust execution layer with order state reconciliation and retry logic.
- Multi-strategy framework with backtesting against historical data.
- Deployment runbook (containerization + monitoring) for team handoff.

## Completed
- YES/NO token mapping from outcome metadata to avoid order assumptions.
- Portfolio PnL wiring into risk limits with daily and per-market halts.
- Paper simulation now processes only new trades per loop.
- Order book normalization before pricing decisions.
- Tests for strategy quoting, risk gating, and paper fills.
- Tests for live-mode risk halts with a lightweight LiveExecutor mock.
- Enhanced scanner scoring with recent trades, volatility, and time-to-settlement weighting.
- Added taker mode, more aggressive quoting knobs, and market snapshot visibility in the dashboard.
- Added strategy validation stats with edge gating and delayed signal evaluation.
- Live fill reconciliation so portfolio + risk are accurate in live mode.
- Added live open-order caching for dashboard fidelity and reduced API calls.
- Added market-specific order throttling and per-market cooldowns.
- Added webhook alerting for risk events, PnL thresholds, and stale reconciliation.
- Added live order retries and reconciliation updates for execution robustness.
- Added a basic backtest harness for offline signal evaluation.
- Added richer backtest outputs (PnL simulation and trade logs).
- Added backtest equity plotting (PNG/HTML) and a dashboard backtest tab.
