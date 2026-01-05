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
