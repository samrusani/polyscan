# Known Issues

- Live trading mode polls fills via the CLOB client, but if the client does not expose a fill endpoint, live reconciliation will be skipped.
- Risk halts in live mode cancel orders but do not guarantee position flattening without an execution-side close.
- Paper simulation can reprocess trades if the feed truncates the trade list (last 100), which may still overfill in rare cases.
- Recent trade and volatility metrics depend on the CLOB trade endpoint; if unavailable, those fields remain unset and trade-based filters are skipped.
- Signal evaluation stats use mid-price movement after a fixed delay; they do not account for actual fills or settlement outcomes.
- Live open-order cache may drift if the CLOB API is unavailable during refresh; the next successful refresh will correct it.
- Live order retries are not idempotent; if a request succeeds but the response is lost, a retry can create a duplicate order.
- Backtest PnL ignores fees, slippage, and partial fills; results are directional only.
