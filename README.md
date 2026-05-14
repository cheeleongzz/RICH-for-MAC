# RICH

A fully automated US-equity stock recommender that runs daily on Windows or macOS. RICH ingests financial data from the [Financial Modeling Prep API](https://financialmodelingprep.com/), applies a structured fundamental-analysis pipeline across ~1,000 eligible stocks, and outputs a single daily recommendation — or no recommendation when nothing clears all quality gates. Every decision is stored in SQLite for full auditability. The system has no connection to any brokerage or execution platform.

**Stack:** Python 3.13 · SQLite · FMP API · Windows Task Scheduler / macOS launchd

---

## Key Components

| Module | Role |
|---|---|
| `pipeline.py` | End-to-end orchestration (universe → screen → score → cooldown → store) |
| `universe.py` | Builds the daily eligible universe from NASDAQ/NYSE/AMEX |
| `screener.py` + `beneish.py` | Hard rejection rules including the Beneish M-Score earnings-manipulation gate |
| `scoring.py` | Cross-sectional z-score model across Quality (35%), Growth (40%), and Value/Risk (25%) sleeves |
| `valuation.py` | Sector-median PE overlay — shadow mode, not yet affecting picks |
| `portfolio.py` | Read-only portfolio engine tracking entry/exit signals |
| `track_performance.py` | Measures pick returns against the SPY benchmark |
| `data/storage.py` | SQLite schema, migrations, and insert logic |
| `data/fetcher.py` | FMP API client with per-day response caching and timeout hardening |

---

## Documentation

Full methodology, architecture, factor definitions, and implementation status are in:

**[RICH\_METHODOLOGY\_AND\_STATUS.md](RICH_METHODOLOGY_AND_STATUS.md)**

That document is the best starting point for understanding the system. Read it before the code.

---

## Status

| Phase | Description | Status |
|---|---|---|
| Phase 1 | Universe hardening (sector exclusion, ADR guard) | ✅ Live |
| Phase 2 | Beneish M-Score hard gate | ✅ Live |
| Phase 3 | Quality / Growth / Value-Risk scoring sleeves | ✅ Live |
| Phase 4 | Cross-sectional z-score normalisation | ✅ Live |
| Phase 5 | Portfolio engine | 🔵 Read-only |
| Phase 6 | Performance tracking vs SPY | ✅ Live |
| Valuation overlay | Sector-median PE shadow rank | 🔵 Shadow until 2026-06-02 |

---

## Running

```bash
# Daily run (also triggered automatically by Task Scheduler / launchd)
python run_daily.py

# View today's pick
python report_today.py

# Update performance tracking
python track_performance.py

# View portfolio engine state
python run_portfolio.py --show
```

Requires a `.env` file with `FMP_API_KEY=<your_key>`. See `.env.example`.

### macOS quickstart

```bash
# 1. Create .venv and install requirements
bash scripts/bootstrap_venv.sh

# 2. Add your FMP key
cp .env.example .env
$EDITOR .env

# 3. Run once manually
./run_daily.sh
./view_today.sh

# 4. Install the launchd agent (08:00 + 12:00 MYT, converted to local tz)
bash scripts/install_scheduler.sh

# Uninstall:
bash scripts/uninstall_scheduler.sh
```

The launchd agent runs `run_daily.py` from `./.venv/bin/python`; stdout/stderr
land in `logs/launchd.out` and `logs/launchd.err`. Re-run `install_scheduler.sh`
after a timezone change (e.g., travel) to re-render the local trigger times.
