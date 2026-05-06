"""Phase 6: track pick performance vs SPY benchmark.

Run manually or on a schedule:
    python track_performance.py

Writes/updates the pick_outcomes table in cache.db with one row per past
daily pick. Re-running is safe (INSERT OR REPLACE). Pre-Phase-6 picks that
have no stored pick_price are backfilled from FMP historical-price-eod.
"""
from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

from config import CACHE_DB
from data.fetcher import FMPClient
from data.storage import connect, init_db

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pick_outcomes (
    run_date        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    pick_price      REAL,
    exit_price      REAL,
    hold_days       INTEGER,
    return_pct      REAL,
    spy_return_pct  REAL,
    alpha           REAL,
    as_of_date      TEXT NOT NULL,
    PRIMARY KEY (run_date, symbol)
);
"""

_COLS = [
    "run_date", "symbol", "pick_price", "exit_price",
    "hold_days", "return_pct", "spy_return_pct", "alpha", "as_of_date",
]


def _init(db: Path) -> None:
    init_db(db)  # runs daily_picks migrations (adds pick_price if absent)
    with connect(db) as c:
        c.executescript(_SCHEMA)


def _past_picks(db: Path) -> list[dict]:
    with connect(db) as c:
        rows = c.execute(
            "SELECT run_date, symbol, pick_price "
            "FROM daily_picks WHERE is_daily_pick=1 ORDER BY run_date",
        ).fetchall()
    return [dict(r) for r in rows]


def _close_at_or_before(history: list[dict], target_date: str) -> float | None:
    """Return close on target_date, or the closest prior trading day (history is descending)."""
    for row in history:
        if row.get("date", "") <= target_date:
            return row.get("close")
    return None


def track(db: Path = CACHE_DB) -> list[dict]:
    _init(db)
    client = FMPClient()
    today_str = date.today().isoformat()

    picks = _past_picks(db)
    if not picks:
        log.info("no past picks found in daily_picks")
        return []
    log.info("tracking %d picks as of %s", len(picks), today_str)

    # Fetch SPY history once; FMP returns descending date order.
    # light=False gives the full OHLCV response with a standard "close" field.
    log.info("fetching SPY historical prices...")
    spy_hist = client.historical_price("SPY", light=False)
    spy_current = spy_hist[0]["close"] if spy_hist else None
    if spy_current is None:
        log.error("could not fetch SPY price; aborting")
        return []
    log.info("    SPY current close = %.4f", spy_current)

    outcomes: list[dict] = []
    for pick in picks:
        run_date: str = pick["run_date"]
        symbol: str = pick["symbol"]
        pick_price: float | None = pick["pick_price"]

        # Backfill pick_price for pre-Phase-6 rows that have no stored price.
        if pick_price is None:
            try:
                hist = client.historical_price(symbol, light=False)
                pick_price = _close_at_or_before(hist, run_date)
            except Exception as e:
                log.warning("backfill pick_price failed  %s %s: %s", symbol, run_date, e)

        # Current exit price (most recent quote).
        exit_price: float | None = None
        try:
            exit_price = client.quote(symbol).get("price")
        except Exception as e:
            log.warning("quote failed  %s: %s", symbol, e)

        # SPY price on or immediately before the pick date.
        spy_at_pick = _close_at_or_before(spy_hist, run_date)
        hold_days = (date.today() - date.fromisoformat(run_date)).days

        return_pct: float | None = None
        if pick_price and exit_price:
            return_pct = round((exit_price - pick_price) / pick_price * 100, 4)

        spy_return_pct: float | None = None
        if spy_at_pick and spy_current:
            spy_return_pct = round((spy_current - spy_at_pick) / spy_at_pick * 100, 4)

        alpha: float | None = None
        if return_pct is not None and spy_return_pct is not None:
            alpha = round(return_pct - spy_return_pct, 4)

        row = {
            "run_date": run_date,
            "symbol": symbol,
            "pick_price": pick_price,
            "exit_price": exit_price,
            "hold_days": hold_days,
            "return_pct": return_pct,
            "spy_return_pct": spy_return_pct,
            "alpha": alpha,
            "as_of_date": today_str,
        }
        outcomes.append(row)

        log.info(
            "%-12s %-6s  pick=%8s  exit=%8s  ret=%+7s%%  spy=%+7s%%  alpha=%+7s%%  days=%d",
            run_date, symbol,
            f"{pick_price:.2f}" if pick_price else "n/a",
            f"{exit_price:.2f}" if exit_price else "n/a",
            f"{return_pct:.2f}" if return_pct is not None else "n/a",
            f"{spy_return_pct:.2f}" if spy_return_pct is not None else "n/a",
            f"{alpha:.2f}" if alpha is not None else "n/a",
            hold_days,
        )

    sql = (
        f"INSERT OR REPLACE INTO pick_outcomes ({','.join(_COLS)}) "
        f"VALUES ({','.join('?' * len(_COLS))})"
    )
    with connect(db) as c:
        c.executemany(sql, [tuple(o[k] for k in _COLS) for o in outcomes])
    log.info("wrote %d rows to pick_outcomes", len(outcomes))
    return outcomes


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    track()
