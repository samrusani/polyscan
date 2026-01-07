# Polymarket House Bot

A Python-based market maker and scanner for Polymarket short-duration binary markets.

## Safety Checklist
- [ ] **Repo Only**: All operations occur within the repo.
- [ ] **Paper Default**: Live trading is DISABLED by default.
- [ ] **Risk Limits**: Hard stops for daily loss and inventory implemented.
- [ ] **Clean Exit**: Bot handles shutdown gracefully canceling open orders (in live mode).

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configuration**:
   Copy the example config and edit it (DO NOT COMMIT REAL KEYS):
   ```bash
   cp config/config.example.json config/config.json
   ```
   For live trading, you will also need to populate `.env` (see `.env.example`).

## Usage

### Scanner
Run the market scanner to generate `data/watchlist.json`:
```bash
python main_scanner.py
```
Run the active market scanner (orderbook activity probe) to generate `data/active_watchlist.json`:
```bash
python main_active_scanner.py
```

### Bot (Paper Mode)
Run the bot in paper trading mode:
```bash
python main_bot.py
```

### Bot (Live Mode)
**WARNING**: Real funds at risk.
1. Set `ENABLE_LIVE_TRADING=true` in `.env`
2. Set `"mode": "live"` in `config/config.json`
3. Run:
```bash
python main_bot.py
```

### Backtest (Offline)
Run a simple signal backtest against recorded ticks:
```bash
python main_backtest.py --data backtest_sample.json --token-id tokenA --trades-out backtest_trades.json --trades-csv backtest_trades.csv --equity-out backtest_equity.csv
```
Record live ticks for backtesting:
```bash
python scripts/record_ticks.py --watchlist data/watchlist.json --duration-sec 300 --out backtest_ticks.json
```
Then backtest the recorded file:
```bash
python main_backtest.py --data backtest_ticks.json --infer-tokens --equity-out backtest_equity.csv
```
Run a multi-token backtest:
```bash
python main_backtest.py --data backtest_sample.json --tokens tokenA,tokenB --equity-out backtest_equity.csv
```
Use `--infer-tokens` to auto-detect token IDs from the tick file.
Run a parameter sweep:
```bash
python main_backtest.py --data backtest_sample.json --token-id tokenA --sweep backtest_sweep.example.json --sweep-out backtest_sweep.csv
```

Plot the equity curve:
```bash
python scripts/plot_backtest.py --equity-csv backtest_equity.csv --out backtest_equity.png
```
Render an interactive HTML plot:
```bash
python scripts/plot_backtest.py --equity-csv backtest_equity.csv --html-out backtest_equity.html
```

## Structure
- `src/scanner`: Market discovery and ranking
- `src/bot`: Trading logic, signals, risk engine, execution
- `src/infra`: Config, logging, utilities

## Documentation
- Primary docs: `docs/README.md`
- Roadmap: `docs/ROADMAP.md`
- Known issues: `docs/KNOWN_ISSUES.md`
- Version log: `docs/VERSIONS.md`

Documentation update rule: every change must update the docs and add a new entry in `docs/VERSIONS.md`.
