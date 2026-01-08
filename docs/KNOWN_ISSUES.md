# Known Issues

- Live trading mode polls fills via the CLOB client, but if the client does not expose a fill endpoint, live reconciliation will be skipped.
- Risk halts in live mode cancel orders but do not guarantee position flattening without an execution-side close.
- Paper simulation can reprocess trades if the feed truncates the trade list (last 100), which may still overfill in rare cases.
- Recent trade and volatility metrics depend on the CLOB trade endpoint; if unavailable, those fields remain unset and trade-based filters are skipped.
- Signal evaluation stats use mid-price movement after a fixed delay; they do not account for actual fills or settlement outcomes.
- Live open-order cache may drift if the CLOB API is unavailable during refresh; the next successful refresh will correct it.
- Live order retries are not idempotent; if a request succeeds but the response is lost, a retry can create a duplicate order.
- Backtest PnL ignores partial fills and settlement outcomes; results are directional only.
- Backtest fees/slippage are simplified (bps + ticks) and do not model depth, maker/taker tiers, or partial fills.
- Multi-token backtests assume synchronized ticks; mismatched feeds can skew equity timing.
- Recorded ticks are snapshots at an interval and may miss intra-interval book changes.
- Websocket handshake timeouts can result in empty tick files; increase `--ws-open-timeout`, reduce markets, or set `--ws-origin` and `--ws-header` to mimic browser headers.
- HTTP fallback tick recording is slower and may hit rate limits when polling many tokens.
- Trade probing relies on the CLOB trade endpoint and may be rate limited or return sparse data on low-activity markets.
- Orderbook-activity probing polls orderbooks multiple times and can be slow or rate-limited on large token sets.
- Orderbook activity metrics focus on top-of-book changes and may miss deeper liquidity shifts.
- Active scanner can probe both YES and NO tokens, but activity may still be skewed by orderbook sampling lag.
- Mid-price backtest mode is a heuristic and may overstate signal quality vs. trade-driven fair value.
