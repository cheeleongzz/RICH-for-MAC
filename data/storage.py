"""SQLite storage for daily picks. Single source of truth for cooldown lookups."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from config import CACHE_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_picks (
    run_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    company_name TEXT,
    total_score REAL,
    quality_score REAL,
    growth_score REAL,
    value_risk_score REAL,
    recommendation_rank INTEGER,
    is_daily_pick INTEGER NOT NULL DEFAULT 0,
    eligible_for_pick INTEGER NOT NULL DEFAULT 1,
    in_cooldown INTEGER NOT NULL DEFAULT 0,
    cooldown_until TEXT,
    historical_years_available INTEGER,
    top_drivers TEXT,
    bottom_drivers TEXT,
    short_reason TEXT,
    sector_median_pe       REAL,
    fair_value_pe          REAL,
    pe_vs_sector           REAL,
    valuation_adj          REAL,
    valuation_label        TEXT,
    valuation_model_version TEXT,
    total_score_adj                    REAL,
    recommendation_rank_with_valuation INTEGER,
    m_score                            REAL,
    beneish_flag                       INTEGER,
    f_score                            INTEGER,
    novy_marx_gp_assets                REAL,
    -- Growth shadow factors (Phase 3.2; not yet in scoring)
    revenue_cagr_5y  REAL,
    eps_cagr_5y      REAL,
    fcf_cagr_5y      REAL,
    asset_growth     REAL,
    -- Value/Risk shadow factors (Phase 3.3; not yet in scoring)
    ev_ebitda        REAL,
    ps_ratio         REAL,
    peg_ratio        REAL,
    pe_vs_own_history REAL,
    -- Phase 4 diagnostics: V1 linear scores + scoring metadata
    total_score_v1       REAL,
    quality_score_v1     REAL,
    growth_score_v1      REAL,
    value_risk_score_v1  REAL,
    normalization_method TEXT,
    universe_n_at_scoring INTEGER,
    -- Phase 6 performance tracking
    pick_price REAL,
    PRIMARY KEY (run_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_picks_lookup
    ON daily_picks(symbol, is_daily_pick, run_date);
"""

COLUMNS = [
    "run_date", "symbol", "company_name",
    "total_score", "quality_score", "growth_score", "value_risk_score",
    "recommendation_rank", "is_daily_pick", "eligible_for_pick",
    "in_cooldown", "cooldown_until", "historical_years_available",
    "top_drivers", "bottom_drivers", "short_reason",
    # valuation overlay (shadow mode; not used for ranking)
    "sector_median_pe", "fair_value_pe", "pe_vs_sector",
    "valuation_adj", "valuation_label", "valuation_model_version",
    # dual ranking (observation only)
    "total_score_adj", "recommendation_rank_with_valuation",
    # Beneish M-Score gate (Phase 2)
    "m_score", "beneish_flag",
    # Piotroski F-Score + Novy-Marx GP/Assets (Phase 3 Quality, shadow)
    "f_score", "novy_marx_gp_assets",
    # Growth shadow factors (Phase 3.2)
    "revenue_cagr_5y", "eps_cagr_5y", "fcf_cagr_5y", "asset_growth",
    # Value/Risk shadow factors (Phase 3.3)
    "ev_ebitda", "ps_ratio", "peg_ratio", "pe_vs_own_history",
    # Phase 4 diagnostics
    "total_score_v1", "quality_score_v1", "growth_score_v1", "value_risk_score_v1",
    "normalization_method", "universe_n_at_scoring",
    # Phase 6 performance tracking
    "pick_price",
]


@contextmanager
def connect(path: Path = CACHE_DB):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


_MIGRATIONS = [
    # Phase 2
    "ALTER TABLE daily_picks ADD COLUMN m_score REAL",
    "ALTER TABLE daily_picks ADD COLUMN beneish_flag INTEGER",
    # Phase 3 Quality
    "ALTER TABLE daily_picks ADD COLUMN f_score INTEGER",
    "ALTER TABLE daily_picks ADD COLUMN novy_marx_gp_assets REAL",
    # Phase 3.2 Growth shadow
    "ALTER TABLE daily_picks ADD COLUMN revenue_cagr_5y REAL",
    "ALTER TABLE daily_picks ADD COLUMN eps_cagr_5y REAL",
    "ALTER TABLE daily_picks ADD COLUMN fcf_cagr_5y REAL",
    "ALTER TABLE daily_picks ADD COLUMN asset_growth REAL",
    # Phase 3.3 Value/Risk shadow
    "ALTER TABLE daily_picks ADD COLUMN ev_ebitda REAL",
    "ALTER TABLE daily_picks ADD COLUMN ps_ratio REAL",
    "ALTER TABLE daily_picks ADD COLUMN peg_ratio REAL",
    "ALTER TABLE daily_picks ADD COLUMN pe_vs_own_history REAL",
    # Phase 4 diagnostics
    "ALTER TABLE daily_picks ADD COLUMN total_score_v1 REAL",
    "ALTER TABLE daily_picks ADD COLUMN quality_score_v1 REAL",
    "ALTER TABLE daily_picks ADD COLUMN growth_score_v1 REAL",
    "ALTER TABLE daily_picks ADD COLUMN value_risk_score_v1 REAL",
    "ALTER TABLE daily_picks ADD COLUMN normalization_method TEXT",
    "ALTER TABLE daily_picks ADD COLUMN universe_n_at_scoring INTEGER",
    # Phase 6 performance tracking
    "ALTER TABLE daily_picks ADD COLUMN pick_price REAL",
]


def _migrate_db(path: Path) -> None:
    """Add new columns to an existing DB without dropping data."""
    with connect(path) as c:
        for sql in _MIGRATIONS:
            try:
                c.execute(sql)
            except Exception:
                pass  # column already exists


def init_db(path: Path = CACHE_DB) -> None:
    with connect(path) as c:
        c.executescript(SCHEMA)
    _migrate_db(path)


def insert_picks(rows: list[dict], path: Path = CACHE_DB) -> int:
    placeholders = ",".join("?" * len(COLUMNS))
    sql = (
        f"INSERT OR REPLACE INTO daily_picks ({','.join(COLUMNS)}) "
        f"VALUES ({placeholders})"
    )
    with connect(path) as c:
        c.executemany(sql, [tuple(r.get(k) for k in COLUMNS) for r in rows])
    return len(rows)


def cooldown_map(today: date, cooldown_days: int,
                 path: Path = CACHE_DB) -> dict[str, str]:
    """Return {symbol: cooldown_until_iso} for symbols still in cooldown today."""
    cutoff = (today - timedelta(days=cooldown_days)).isoformat()
    with connect(path) as c:
        rows = c.execute(
            "SELECT symbol, MAX(run_date) AS last_pick FROM daily_picks "
            "WHERE is_daily_pick=1 AND run_date > ? GROUP BY symbol",
            (cutoff,),
        ).fetchall()
    out: dict[str, str] = {}
    for r in rows:
        last = date.fromisoformat(r["last_pick"])
        out[r["symbol"]] = (last + timedelta(days=cooldown_days)).isoformat()
    return out


def fetch_run(run_date: str, path: Path = CACHE_DB) -> list[dict]:
    with connect(path) as c:
        rows = c.execute(
            "SELECT * FROM daily_picks WHERE run_date=? ORDER BY recommendation_rank",
            (run_date,),
        ).fetchall()
    return [dict(r) for r in rows]
