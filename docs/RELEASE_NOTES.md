# Release Notes

## v0.5.48 (2026-01-12)

### Short Highlights
- Added YES/NO arbitrage scanner with near-arb reporting and a time-series log.
- Added Up/Down and Arb tabs in the dashboard with links and plots.
- Expanded up/down scanner to support YES/NO thresholds and SOL/XRP.
- Active scanner can bypass rank filters, enrich orderbooks, and filter by max spread.

### Full Notes
- New up/down scanner that estimates fair value from external spot prices.
- YES/NO threshold markets mapped into up/down signals using question heuristics.
- Arb scanner detects sum-of-asks opportunities and logs near-arb snapshots.
- Activity scan can bypass rank filters, probe more markets, and enrich with spreads.
- Dashboard shows up/down watchlist links and arb near-arb monitoring.

### Config Additions
- `price_feed` and `updown_scanner` settings for external price modeling.
- `arb_scanner` settings for fee buffers, near-arb logging, and depth filters.
- `scanner.activity_bypass_rank_filters`, `scanner.activity_enrich_orderbooks`, and `scanner.activity_max_spread`.

### Migration Notes
- Active scan now defaults to writing `data/watchlist.json`; update any scripts that expect `data/active_watchlist.json`.
- Arb scan logging creates `data/arb_near_arb_log.jsonl`; rotate the file if it grows.
- Up/down scanner adds new output file `data/updown_watchlist.json`.

### Suggested Checks
- `python main_updown_scanner.py`
- `python main_arb_scanner.py`
- `streamlit run dashboard.py`
