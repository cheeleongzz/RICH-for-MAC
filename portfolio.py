"""Read-only portfolio engine.

Reads from daily_picks (written by pipeline.py); writes only to
portfolio_holdings and portfolio_runs. Never touches pipeline.py,
scoring.py, or run_daily.py.

Entry rules  : f_score >= 6  AND  pe_vs_own_history < 1.0 (stocks without
               this field are skipped — insufficient PE history).
Exit rules   : hard  — beneish_flag = 1  OR  f_score <= HARD_EXIT_FSCORE
               soft  — held >= SOFT_HOLD_DAYS (12 weeks)
Sizing       : equal-weight, max MAX_HOLDINGS positions. New slots are filled
               by the highest-total_score qualifying candidates from the last
               CANDIDATE_LOOKBACK days of daily_picks.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from config import CACHE_DB

# ── Tuneable constants ────────────────────────────────────────────────────────
MIN_FSCORE_ENTRY   = 6      # Piotroski F-Score floor for entry
MAX_PE_VS_OWN_HIST = 1.0   # must be below own-history PE median to enter
HARD_EXIT_FSCORE   = 3      # F-Score at-or-below this → hard exit
SOFT_HOLD_DAYS     = 84    # 12 weeks; soft exit threshold
MAX_HOLDINGS       = 30
CANDIDATE_LOOKBACK = 30    # days of daily_picks history to scan for entries
EXIT_DATA_WINDOW   = SOFT_HOLD_DAYS + 30  # how far back to fetch latest pick data

# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_holdings (
    symbol          TEXT NOT NULL,
    entry_date      TEXT NOT NULL,
    entry_score     REAL,
    f_score         INTEGER,
    pe_vs_own_hist  REAL,
    status          TEXT NOT NULL DEFAULT 'active',
    exit_date       TEXT,
    exit_reason     TEXT,
    PRIMARY KEY (symbol, entry_date)
);

CREATE TABLE IF NOT EXISTS portfolio_runs (
    run_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date          TEXT NOT NULL,
    action            TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    reason            TEXT,
    total_score       REAL,
    f_score           INTEGER,
    pe_vs_own_history REAL,
    beneish_flag      INTEGER,
    notes             TEXT
);

CREATE INDEX IF NOT EXISTS idx_ph_status ON portfolio_holdings(status, symbol);
CREATE INDEX IF NOT EXISTS idx_pr_date   ON portfolio_runs(run_date);
"""

_RUN_COLS = [
    "run_date", "action", "symbol", "reason",
    "total_score", "f_score", "pe_vs_own_history", "beneish_flag", "notes",
]


# ── DB helpers ────────────────────────────────────────────────────────────────
@contextmanager
def _connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


def _load_active(db_path: Path) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_holdings WHERE status='active' ORDER BY entry_date"
        ).fetchall()
    return [dict(r) for r in rows]


def _latest_picks_batch(symbols: list[str], since: str, db_path: Path) -> dict[str, dict]:
    """Return the most recent daily_picks row for each symbol, looking back to `since`."""
    if not symbols:
        return {}
    ph = ",".join("?" * len(symbols))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT dp.*
            FROM daily_picks dp
            JOIN (
                SELECT symbol, MAX(run_date) AS latest
                FROM daily_picks
                WHERE symbol IN ({ph}) AND run_date >= ?
                GROUP BY symbol
            ) t ON dp.symbol = t.symbol AND dp.run_date = t.latest
            """,
            (*symbols, since),
        ).fetchall()
    return {r["symbol"]: dict(r) for r in rows}


def _entry_candidates(since: str, exclude: set[str], db_path: Path) -> list[dict]:
    """Most-recent daily_picks row per symbol that meets entry rules, ranked by total_score.

    Excludes symbols already in `exclude` (active holdings that weren't exited).
    Stocks with NULL pe_vs_own_history are skipped (insufficient PE history).
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT dp.*
            FROM daily_picks dp
            JOIN (
                SELECT symbol, MAX(run_date) AS latest
                FROM daily_picks
                WHERE run_date >= ?
                GROUP BY symbol
            ) t ON dp.symbol = t.symbol AND dp.run_date = t.latest
            WHERE dp.f_score >= ?
              AND dp.pe_vs_own_history IS NOT NULL
              AND dp.pe_vs_own_history < ?
            ORDER BY dp.total_score DESC
            """,
            (since, MIN_FSCORE_ENTRY, MAX_PE_VS_OWN_HIST),
        ).fetchall()
    return [dict(r) for r in rows if r["symbol"] not in exclude]


# ── Business logic ────────────────────────────────────────────────────────────
def _check_exit(holding: dict, latest: dict | None, today: date) -> str | None:
    """Return an exit reason code, or None if the holding should be kept."""
    if latest:
        if latest.get("beneish_flag") == 1:
            return "BENEISH_HARD"
        f = latest.get("f_score")
        if f is not None and f <= HARD_EXIT_FSCORE:
            return "FSCORE_HARD"
    held_days = (today - date.fromisoformat(holding["entry_date"])).days
    if held_days >= SOFT_HOLD_DAYS:
        return "SOFT_12W"
    return None


def _make_run_row(
    run_date: str,
    action: str,
    symbol: str,
    reason: str | None,
    data: dict | None,
    notes: str | None,
) -> dict:
    d = data or {}
    return {
        "run_date":          run_date,
        "action":            action,
        "symbol":            symbol,
        "reason":            reason,
        "total_score":       d.get("total_score"),
        "f_score":           d.get("f_score"),
        "pe_vs_own_history": d.get("pe_vs_own_history"),
        "beneish_flag":      d.get("beneish_flag"),
        "notes":             notes,
    }


# ── Public API ────────────────────────────────────────────────────────────────
def run(
    today: date | None = None,
    db_path: Path = CACHE_DB,
) -> dict[str, Any]:
    """Evaluate exits and entries; persist changes; return a result summary."""
    today = today or date.today()
    run_date  = today.isoformat()
    since_exit  = (today - timedelta(days=EXIT_DATA_WINDOW)).isoformat()
    since_entry = (today - timedelta(days=CANDIDATE_LOOKBACK)).isoformat()

    _init(db_path)

    # ── 1. Active holdings + latest pick data ─────────────────────────────
    active         = _load_active(db_path)
    active_symbols = {h["symbol"] for h in active}
    latest_by_sym  = _latest_picks_batch(list(active_symbols), since_exit, db_path)

    # ── 2. Collect exits ──────────────────────────────────────────────────
    exits: list[tuple[dict, str, dict | None]] = []
    for h in active:
        latest = latest_by_sym.get(h["symbol"])
        reason = _check_exit(h, latest, today)
        if reason:
            exits.append((h, reason, latest))

    exited_symbols = {h["symbol"] for h, _, _ in exits}

    # ── 3. Apply exits in one write ───────────────────────────────────────
    if exits:
        with _connect(db_path) as conn:
            for h, reason, _ in exits:
                conn.execute(
                    """UPDATE portfolio_holdings
                       SET status='exited', exit_date=?, exit_reason=?
                       WHERE symbol=? AND entry_date=?""",
                    (run_date, reason, h["symbol"], h["entry_date"]),
                )

    # ── 4. Find + apply entries ───────────────────────────────────────────
    remaining_symbols = active_symbols - exited_symbols
    slots      = max(0, MAX_HOLDINGS - len(remaining_symbols))
    candidates = _entry_candidates(since_entry, remaining_symbols, db_path) if slots > 0 else []
    new_entries = candidates[:slots]

    if new_entries:
        with _connect(db_path) as conn:
            for c in new_entries:
                conn.execute(
                    """INSERT OR IGNORE INTO portfolio_holdings
                       (symbol, entry_date, entry_score, f_score, pe_vs_own_hist, status)
                       VALUES (?, ?, ?, ?, ?, 'active')""",
                    (
                        c["symbol"], run_date,
                        c.get("total_score"), c.get("f_score"), c.get("pe_vs_own_history"),
                    ),
                )

    # ── 5. Build run log ──────────────────────────────────────────────────
    log_rows: list[dict] = []

    for h, reason, latest in exits:
        action = "EXIT_HARD" if reason != "SOFT_12W" else "EXIT_SOFT"
        held   = (today - date.fromisoformat(h["entry_date"])).days
        log_rows.append(_make_run_row(run_date, action, h["symbol"], reason, latest,
                                      f"held {held}d"))

    new_entry_symbols = {c["symbol"] for c in new_entries}
    for c in new_entries:
        log_rows.append(_make_run_row(
            run_date, "ADD", c["symbol"], "ENTRY_QUAL", c,
            f"f={c.get('f_score')} pe_hist={c.get('pe_vs_own_history')}",
        ))

    for h in active:
        sym = h["symbol"]
        if sym not in exited_symbols and sym not in new_entry_symbols:
            latest = latest_by_sym.get(sym)
            held   = (today - date.fromisoformat(h["entry_date"])).days
            log_rows.append(_make_run_row(run_date, "HOLD", sym, None, latest,
                                          f"held {held}d"))

    if not log_rows:
        log_rows.append(_make_run_row(
            run_date, "NO_CHANGE", "", None, None,
            "no active holdings and no qualifying entry candidates",
        ))

    # ── 6. Persist run log ────────────────────────────────────────────────
    ph  = ",".join("?" * len(_RUN_COLS))
    sql = f"INSERT INTO portfolio_runs ({','.join(_RUN_COLS)}) VALUES ({ph})"
    with _connect(db_path) as conn:
        conn.executemany(sql, [tuple(r.get(k) for k in _RUN_COLS) for r in log_rows])

    final_holdings = _load_active(db_path)
    return {
        "run_date":       run_date,
        "exits":          [(h["symbol"], reason) for h, reason, _ in exits],
        "entries":        [c["symbol"] for c in new_entries],
        "holdings":       final_holdings,
        "holdings_count": len(final_holdings),
    }


def active_holdings(db_path: Path = CACHE_DB) -> list[dict]:
    """Convenience: return current active holdings without running a cycle."""
    _init(db_path)
    return _load_active(db_path)
