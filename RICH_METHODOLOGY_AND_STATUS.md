# RICH — Methodology & Implementation Status

> **Start here.** This is the authoritative project overview for RICH — a fully automated US-equity stock recommender built on Python, SQLite, and the FMP API. It describes the investment philosophy, the complete pipeline architecture, the factor scoring model, and the current implementation status of every phase. If you are reading the code for the first time, read this document before anything else.

**Last updated:** 2026-05-06  
**Stack:** Python 3.13 · SQLite · FMP API · Windows Task Scheduler (MYT UTC+8)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Methodology — The 16-Step Framework](#3-methodology--the-16-step-framework)
4. [Implementation Status](#4-implementation-status)
5. [Observability & Tooling](#5-observability--tooling)
6. [Key Files Reference](#6-key-files-reference)

---

## 1. Overview

RICH is a **fully automated, pure-fundamentals stock picker** that runs every trading day on a Windows machine. It ingests raw financial data from the FMP API, filters a broad US-equity universe down to a single daily recommendation, and writes every decision — score, flag, and reject reason — to SQLite for full auditability.

The system is systematic and rules-based: no human intervention is required after setup, and no subjective judgement enters the model. It favours earnings quality and genuine profitability over growth narratives. When no candidate clears all gates, the system outputs no recommendation rather than being forced to pick.

RICH generates recommendations, not orders. It has no connection to any brokerage or execution system.

**Daily schedule:**

| Task | Time (MYT) | Trigger |
|---|---|---|
| `\RICH_Daily_0800_MYT` | 08:00 | `run_daily.bat` (primary) |
| `\RICH_Daily_1200_MYT` | 12:00 | `py.exe run_daily.py` (fallback) |

Typical runtime: **10–15 minutes**, dominated by FMP API calls. A same-day rerun completes in under 1 second via the per-day JSON cache.

---

## 2. Architecture

### 2.1 Pipeline Flow

```
FMP API
  │
  ▼
universe.py ─────────────────────────────────────────────────────────
  │  NASDAQ + NYSE + AMEX via company_screener
  │  Drop: preferred shares / warrants / dual-listed shells
  │  Drop: Financial Services / Utilities / Real Estate      [Phase 1]
  │  Drop: non-US domicile (ADR guard)                       [Phase 1]
  │  Drop: market cap < $2 B or daily dollar volume < $5 M
  ▼
  ~1,000 – 1,150 eligible stocks
  │
  ▼  [Pass 1 — ThreadPoolExecutor, 6 workers, capped at 20]
factors.py ──────────────────────────────────────────────────────────
  │  FMPClient fetches: income_statement / balance_sheet /
  │    cash_flow / ratios / key_metrics / financial_growth
  │  Per-day JSON cache (fmp_cache_YYYY-MM-DD.json) — zero
  │  duplicate API calls on same-day reruns
  │
  ├─→ Scored metrics:  ROE, ROA, GPM, OPM, OCF/NI, D/E, PE, revGrowth
  ├─→ Quality extras:  f_score, novy_marx_gp_assets
  ├─→ Growth extras:   revenue_cagr_5y, eps_cagr_5y, fcf_cagr_5y, asset_growth
  ├─→ Value/Risk:      ev_ebitda, ps_ratio, pe_vs_own_history
  ├─→ Manipulation:    m_score, beneish_flag  (feeds screener gate)
  └─→ Shadow-only:     peg_ratio
  │
screener.py ─────────────────────────────────────────────────────────
  │  Hard reject rules (binary pass/fail):
  │    HIST_LT_5 · REV_NONPOSITIVE · NI_OCF_NONPOSITIVE
  │    MISSING_FIELDS · BENEISH_FLAG                         [Phase 2]
  │
  ▼  [Pass 2 — single-threaded across all passing candidates]
scoring.py ──────────────────────────────────────────────────────────
  │  Cross-sectional z-score (±3σ clip → [0, 100])           [Phase 4]
  │  total_score = 0.35·Q + 0.40·G + 0.25·VR  (WEIGHTS_V2)
  │  V1 linear scores retained as diagnostic columns
  │
valuation.py ────────────────────────────────────────────────────────
  │  Sector-median PE overlay → valuation_adj (±10 pts cap)
  │  Produces total_score_adj + recommendation_rank_with_valuation
  │  ⚠ SHADOW ONLY — does not affect the daily pick
  │
cooldown.py ─────────────────────────────────────────────────────────
  │  60-day cooldown prevents repeat picks
  │  Top-ranked non-cooldown stock → is_daily_pick = 1
  │  EOD close price fetched for daily pick → pick_price     [Phase 6]
  │
data/storage.py ─────────────────────────────────────────────────────
  │  INSERT OR REPLACE into daily_picks (SQLite, 43 columns)
  │  Also manages: portfolio_holdings · portfolio_runs       [Phase 5]
  │                pick_outcomes                             [Phase 6]
  │
logging_utils.py ────────────────────────────────────────────────────
     logs/YYYY-MM-DD.log  ·  logs/run_metrics.csv
```

### 2.2 Key Modules

| Module | Role |
|---|---|
| `run_daily.py` | Entry point — initialises logging and calls `pipeline.run()` |
| `pipeline.py` | Orchestration across 7 stages; enforces worker cap and pick-price fetch |
| `universe.py` | Universe construction: exchange, liquidity, sector, and ADR filters |
| `factors.py` | FMP data fetching and per-ticker factor extraction; thread-safe JSON cache |
| `screener.py` | Hard rejection rules including the Beneish gate |
| `beneish.py` | Standard 8-variable Beneish M-Score model |
| `piotroski.py` | 9-signal Piotroski F-Score model |
| `scoring.py` | Cross-sectional z-score scoring: `RULES`, `WEIGHTS_V2`, `score_cross_sectional()` |
| `valuation.py` | Sector-median PE overlay — shadow mode only |
| `cooldown.py` | 60-day cooldown map derived from `daily_picks` |
| `data/fetcher.py` | `FMPClient` — all FMP `/stable/` endpoints; tenacity retries; `DEFAULT_TIMEOUT = (10, 30)` |
| `data/storage.py` | `SCHEMA`, `COLUMNS`, `_MIGRATIONS` — single source of truth for the DB shape |
| `portfolio.py` | Portfolio engine: entry/exit/hold rules *(read-only, Phase 5)* |
| `track_performance.py` | Pick return vs SPY tracking; writes `pick_outcomes` *(Phase 6)* |

### 2.3 Database Schema (`data/cache.db`)

**`daily_picks`** — 43 columns, PK `(run_date, symbol)`

| Column group | Columns |
|---|---|
| Identity | `run_date`, `symbol`, `company_name` |
| Scores (V2) | `total_score`, `quality_score`, `growth_score`, `value_risk_score` |
| Ranking | `recommendation_rank`, `is_daily_pick`, `eligible_for_pick`, `in_cooldown`, `cooldown_until` |
| Universe | `historical_years_available` |
| Explanation | `top_drivers`, `bottom_drivers`, `short_reason` |
| Valuation overlay *(shadow)* | `sector_median_pe`, `fair_value_pe`, `pe_vs_sector`, `valuation_adj`, `valuation_label`, `valuation_model_version`, `total_score_adj`, `recommendation_rank_with_valuation` |
| Beneish | `m_score`, `beneish_flag` |
| Quality extras | `f_score`, `novy_marx_gp_assets` |
| Growth extras | `revenue_cagr_5y`, `eps_cagr_5y`, `fcf_cagr_5y`, `asset_growth` |
| Value/Risk extras | `ev_ebitda`, `ps_ratio`, `peg_ratio`, `pe_vs_own_history` |
| V1 diagnostics | `total_score_v1`, `quality_score_v1`, `growth_score_v1`, `value_risk_score_v1` |
| Metadata | `normalization_method`, `universe_n_at_scoring` |
| Performance | `pick_price` |

**`pick_outcomes`** — PK `(run_date, symbol)`

`run_date · symbol · pick_price · exit_price · hold_days · return_pct · spy_return_pct · alpha · as_of_date`

**`portfolio_holdings`** · **`portfolio_runs`** — Portfolio engine tables *(Phase 5, read-only)*

---

## 3. Methodology — The 16-Step Framework

### 3.1 Investment Philosophy

RICH is a **pure-fundamentals, anti-glamour** system.

- **No momentum. No sentiment. No macro.** The model uses only audited financial statement data.
- **Anti-hype by construction.** High-multiple story stocks are penalised by the Value/Risk sleeve and the PE-vs-own-history signal.
- **Earnings quality over earnings level.** The Beneish gate and Piotroski F-Score specifically filter out companies that report profits but cannot back them with cash flow.
- **One pick per day, or none.** The system is never forced to recommend; an empty position is a valid output.
- **Full auditability.** Every score, flag, and rejection reason is persisted. Any pick can be traced through all intermediate steps after the fact.

---

### Stage A — Universe Construction (Steps 1–3)

| Filter | Logic | Code |
|---|---|---|
| Exchange | NASDAQ + NYSE + AMEX via FMP `company_screener` | `universe.py` |
| Liquidity floor | Market cap ≥ **$2 B** and daily dollar volume ≥ **$5 M** | `universe.py` |
| Symbol hygiene | Drop preferred shares (`.PR`), warrants (`.WT`), dual-listed shells | `universe.py` |
| **Sector exclusion** | Drop Financial Services, Utilities, Real Estate — structurally incompatible with RICH's factor model | `config.py`, `universe.py` |
| **ADR guard** | Secondary `country` field check; rejects non-US-domiciled companies regardless of listing exchange | `universe.py` |

> **Typical eligible universe:** ~1,000–1,150 stocks per run, down from ~1,550 raw before sector exclusion.

---

### Stage B — Hard Screens (Steps 4–8)

All rules are **binary**. A single failure eliminates the stock from scoring entirely.

| Reject code | Rule | Implementation |
|---|---|---|
| `HIST_LT_5` | Fewer than 5 years of financial history | `screener.py` |
| `REV_NONPOSITIVE` | Revenue ≤ 0 | `screener.py` |
| `NI_OCF_NONPOSITIVE` | Both net income **and** operating cash flow ≤ 0 | `screener.py` |
| `MISSING_FIELDS` | Any of the 8 core scored metrics is absent | `screener.py` |
| `BENEISH_FLAG` | **Beneish M-Score > −1.78** | `beneish.py` → `screener.py` |

#### Beneish M-Score Gate

The Beneish model uses 8 financial ratios derived from two consecutive years of income, balance sheet, and cash flow statements to estimate the likelihood of earnings manipulation. A score above −1.78 (the published threshold) triggers a hard reject — the stock is excluded from scoring regardless of any other metric. In practice, `BENEISH_FLAG` eliminates roughly 7–8% of the eligible universe per run.

---

### Stage C — Factor Scoring (Steps 9–13)

Scoring uses **cross-sectional z-scores** across all candidates that passed Stage B, not fixed linear ranges. For each metric:

1. Pool all passing-candidate values → compute cross-sectional mean (μ) and std (σ)
2. `z = (v − μ) / σ`, sign-inverted for lower-is-better metrics
3. Clip at **±3σ**
4. Map to **[0, 100]**
5. Average within sleeve → weighted composite

```
total_score = 0.35 · quality_score + 0.40 · growth_score + 0.25 · value_risk_score
```

#### Quality Sleeve — weight 0.35

| Metric | Notes |
|---|---|
| `returnOnEquity` | Core profitability |
| `returnOnAssets` | Asset efficiency |
| `grossProfitMargin` | Pricing power |
| `operatingProfitMargin` | Operating leverage |
| OCF/NI ratio | Cash conversion quality |
| **`f_score`** | Piotroski 9-signal composite (profitability + leverage + efficiency) |
| **`novy_marx_gp_assets`** | Gross profit / total assets — Novy-Marx quality factor |

#### Growth Sleeve — weight 0.40

| Metric | Notes |
|---|---|
| `revenueGrowth` | Latest year-on-year |
| **`revenue_cagr_5y`** | 5-year revenue compound growth |
| **`eps_cagr_5y`** | 5-year EPS compound growth |
| **`fcf_cagr_5y`** | 5-year free cash flow compound growth |
| **`asset_growth`** | *Inverted penalty* — rapid asset expansion scores lower (Fama-French CMA style) |

CAGR metrics are optional per-ticker: if data is unavailable, the sleeve average is computed from the remaining metrics rather than failing.

#### Value/Risk Sleeve — weight 0.25

| Metric | Direction | Notes |
|---|---|---|
| `debtToEquityRatio` | ↓ lower is better | Leverage |
| `priceEarningsRatio` | ↓ | Traditional PE multiple |
| **`ev_ebitda`** | ↓ | Enterprise multiple; stocks with negative EBITDA are excluded from this metric |
| **`ps_ratio`** | ↓ | Price-to-sales |
| **`pe_vs_own_history`** | ↓ | Current PE divided by the median of ≥3 prior-year positive PEs — a pseudo-CAPE signal |

`peg_ratio` is computed and stored as a shadow column only; it is too sparse and too frequently negative to participate in scoring reliably.

---

### Stage D — Valuation Overlay (Steps 14–15)

> ⚠ **Shadow mode only.** The overlay is computed and stored but does not affect the daily pick.

A sector-median PE model applies a ±10 pt adjustment to produce an alternative composite score and rank. These columns are persisted for observation and will be evaluated against live performance data before any promotion decision.

| Column | Meaning |
|---|---|
| `valuation_adj` | Adjustment, capped at ±10 pts |
| `valuation_label` | `undervalued / fair / overvalued / n/a` |
| `total_score_adj` | `total_score + 0.5 × valuation_adj` |
| `recommendation_rank_with_valuation` | Alternative rank if the overlay were live |

**Decision gate:** On or after **2026-06-02** (~20 trading days of accumulated data), compare alpha from overlay-adjusted picks against alpha from raw-score picks. Promote to live if the overlay shows consistent improvement; recalibrate or remove it otherwise.

---

### Stage E — Cooldown & Selection (Step 16)

- A **60-day cooldown** prevents the same ticker from being selected again within two months
- The highest-scoring stock not in cooldown is designated `is_daily_pick = 1`
- The top-5 rows by score (`TOP_N = 5`) are persisted each run; the daily pick is always included even if it ranks outside the top-5
- The pipeline fetches the most recent EOD close price for the daily pick immediately after selection and stores it as `pick_price` in `daily_picks`

---

## 4. Implementation Status

### Phase Summary

| Phase | Description | Status |
|---|---|---|
| **Phase 1** | Universe hardening — sector exclusion, ADR guard | ✅ Live |
| **Phase 2** | Beneish M-Score hard gate | ✅ Live |
| **Phase 3.1** | Quality sleeve — F-Score + Novy-Marx | ✅ Live |
| **Phase 3.2** | Growth sleeve — 5-year CAGRs + asset growth penalty | ✅ Live |
| **Phase 3.3** | Value/Risk sleeve — EV/EBITDA, PS ratio, PE vs own history | ✅ Live |
| **Phase 4** | Cross-sectional z-score scoring; V2 weights Q=35/G=40/V=25 | ✅ Live |
| **Phase 5** | Portfolio engine — entry/exit/hold cycle | 🔵 Read-only (pending promotion) |
| **Phase 6** | Performance tracking — `pick_outcomes`, alpha vs SPY | ✅ Live |
| **Valuation overlay** | Sector-median PE shadow rank | 🔵 Shadow (decision gate: 2026-06-02) |
| **FMP day-cache** | Per-day JSON cache; zero API calls on same-day rerun | ✅ Live |
| **Timeout hardening** | Split connect/read timeouts; `Timeout` warning log | ✅ Live |

---

### ✅ Phase 1 — Universe Hardening

- NASDAQ + NYSE + AMEX; preferred shares, warrants, and dual-listed shells removed
- **Sector exclusion:** Financial Services, Utilities, Real Estate excluded via `EXCLUDED_SECTORS` in `config.py`
- **ADR guard:** secondary `country` field check applied after the API's own `country=US` filter

---

### ✅ Phase 2 — Beneish M-Score Hard Gate

- `beneish.py` implements the standard 8-variable model using consecutive-year IS/BS/CF data; returns `None` when fewer than 2 years are available
- Applied in `screener.py` immediately after the OCF/NI check: `M-Score > −1.78` → `BENEISH_FLAG` reject
- `m_score` and `beneish_flag` are written to `daily_picks` for every passing and failing candidate

---

### ✅ Phase 3.1 — Quality Sleeve

- `piotroski.py` evaluates all 9 Piotroski signals (profitability, leverage, operating efficiency) and sums them into `f_score` (0–9)
- `novy_marx_gp_assets = grossProfit / totalAssets` computed from the most recent annual data
- Both metrics are active participants in the Quality sleeve score

---

### ✅ Phase 3.2 — Growth Sleeve

- `revenue_cagr_5y`, `eps_cagr_5y`, and `fcf_cagr_5y` computed in `factors.py` and active in scoring
- `asset_growth` included as an inverted penalty: unusually rapid asset expansion is treated as a capital-efficiency warning, not a strength
- Each CAGR metric is optional per-ticker; the sleeve average degrades gracefully on missing data

---

### ✅ Phase 3.3 — Value/Risk Sleeve

- `ev_ebitda`, `ps_ratio`, and `pe_vs_own_history` are active in scoring; all three are inverted (lower is better)
- Stocks with negative EBITDA are excluded from the `ev_ebitda` signal via `_SCORE_FLOOR`
- `pe_vs_own_history` requires at least 3 years of positive prior-year PE data; returns `None` otherwise
- `peg_ratio` is computed and persisted as a shadow column; not used in scoring

---

### ✅ Phase 4 — Cross-Sectional Z-Score Scoring

- Pass 1 (parallel) screens and extracts factors; Pass 2 (single-threaded) scores all passing candidates together in one cross-section
- Z-score normalisation eliminates the fixed-range fragility of the original V1 model
- Final sleeve weights: Q = 35%, G = 40%, VR = 25%
- V1 linear scores retained in `*_score_v1` diagnostic columns for backward comparison

---

### 🔵 Phase 5 — Portfolio Engine *(read-only)*

The portfolio engine is fully implemented in `portfolio.py` and `run_portfolio.py`. It reads from `daily_picks`, applies its own entry/exit rules, and writes results to `portfolio_holdings` and `portfolio_runs`. It does not modify the core pipeline or daily pick selection in any way.

The engine is in **read-only observation mode**: it processes picks and logs signals, but its output is not yet used to drive any external action. Promotion to live use is pending sufficient accumulated pick history to validate the entry/exit rules.

**Entry criteria:**
- Piotroski F-Score ≥ 6
- `pe_vs_own_history < 1.0` (stock trading below its own historical PE median)
- Not flagged by Beneish; not already held

**Exit criteria:**
- Hard exit: `beneish_flag = 1` or `f_score ≤ 3`
- Soft exit: position held for ≥ 84 days

**Parameters:** `MIN_FSCORE_ENTRY=6` · `MAX_PE_VS_OWN_HIST=1.0` · `HARD_EXIT_FSCORE=3` · `SOFT_HOLD_DAYS=84` · `MAX_HOLDINGS=30`

**CLI:** `python run_portfolio.py --show`

---

### ✅ Phase 6 — Performance Tracking

RICH now measures whether its picks outperform the S&P 500.

**`pick_price` in `daily_picks`:** the pipeline fetches the most recent EOD close price for the daily pick via `FMPClient.historical_price()` and stores it at run time. Pre-Phase-6 picks with no stored price are backfilled by `track_performance.py` using the same API.

**`pick_outcomes` table:** updated by running `python track_performance.py`. For each historical `is_daily_pick = 1` row, the script:
1. Resolves `pick_price` (stored or backfilled)
2. Fetches the current price via `FMPClient.quote()` as `exit_price`
3. Fetches SPY historical data once and looks up the SPY close on or before each pick date
4. Computes `return_pct`, `spy_return_pct`, and `alpha = return_pct − spy_return_pct`
5. Writes results with `INSERT OR REPLACE` — safe to re-run at any time

**Early results** *(2 picks; data as of 2026-05-06 — insufficient for statistical conclusions):*

| Pick date | Symbol | Return | SPY | Alpha |
|---|---|---|---|---|
| 2026-05-03 | CALM | +0.81% | +0.43% | **+0.38%** |
| 2026-05-05 | BKNG | 0.00% | 0.00% | 0.00% *(1 day)* |

---

### ✅ Infrastructure — FMP Cache & Timeout Hardening

**Per-day FMP cache**
- `factors.py` writes raw API responses to `data/fmp_cache_YYYY-MM-DD.json`, keyed by symbol
- The cache is thread-safe under `ThreadPoolExecutor` via `threading.Lock`
- Same-day reruns skip all FMP calls and produce byte-identical scores, eliminating non-idempotent rerun divergence

**Timeout hardening** (`data/fetcher.py`)
- `DEFAULT_TIMEOUT = (10, 30)` — a `(connect_s, read_s)` tuple replaces the previous single scalar
- A slow server that connects but delivers bytes slowly can no longer block a worker thread indefinitely
- `requests.Timeout` exceptions are logged as `WARNING` before being re-raised to tenacity (up to 3 retries with exponential backoff)
- `pipeline.py` enforces `max_workers = min(max_workers, 20)` at runtime regardless of the caller argument

---

## 5. Observability & Tooling

### Log Files

| File | Contents |
|---|---|
| `logs/YYYY-MM-DD.log` | Full structured run log — stage-by-stage progress, reject code counts, rank shifts, daily pick |
| `logs/run_metrics.csv` | One row per run: full universe funnel, reject counts by code, per-stage timings, pick symbol and score |

### Scripts

| Script | Purpose |
|---|---|
| `run_daily.py` | Full pipeline run (called by Task Scheduler) |
| `report_today.py` | Print today's pick with valuation overlay detail |
| `daily_view.py` | Read-only pick viewer |
| `run_portfolio.py --show` | Display current portfolio engine holdings |
| `track_performance.py` | Update `pick_outcomes`; print return vs SPY for all picks |

---

## 6. Key Files Reference

### Orientation — read in this order

```
config.py          ← all constants: floors, cooldown, EXCLUDED_SECTORS, weights, API key env var
factors.py         ← canonical factor extraction; extract() returns all scored + shadow fields
screener.py        ← hard rejection rules + Beneish gate; the pass/reject boundary
scoring.py         ← RULES, WEIGHTS_V2, score_cross_sectional(); the scoring contract
data/storage.py    ← SCHEMA, COLUMNS, _MIGRATIONS; any new DB column must appear in all three
```

### Supporting files

| File | Purpose | Notes |
|---|---|---|
| `beneish.py` | 8-variable M-Score model | Do not modify unless fixing the model itself |
| `piotroski.py` | 9-signal F-Score model | Production — feeds the Quality sleeve |
| `pipeline.py` | Orchestration across 7 stages | `_build_row()` must stay in sync with `COLUMNS` |
| `valuation.py` | Sector-PE overlay | Shadow only until the 2026-06-02 decision gate |
| `universe.py` | Universe construction and filters | Rarely needs modification |
| `cooldown.py` | 60-day cooldown logic | — |
| `logging_utils.py` | `setup_logging()` + `append_run_metrics()` | Single source for all log configuration |
| `track_performance.py` | Phase 6 performance tracking | Re-runnable; uses `INSERT OR REPLACE` |
| `data/fetcher.py` | `FMPClient` — all FMP endpoints, retries, timeouts | `DEFAULT_TIMEOUT = (10, 30)` |

### Change-control rule

> **`screener.py`, `scoring.py`, `data/storage.py`, `pipeline.py`** are production-critical.  
> Any modification to these files must be validated with a `pipeline.run(persist=False)` test run before deployment.

---

*Last updated: 2026-05-06 — Phases 1–4 and 6 live; Phase 5 in read-only mode; valuation overlay shadow until 2026-06-02.*
