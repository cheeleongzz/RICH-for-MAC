"""One-off valuation overlay sampler. Run from project root: py check_overlay_samples.py"""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

N_DAYS = 30
MIN_HIGH_SCORE = 85.0

DB = Path("data/cache.db")
cutoff = (date.today() - timedelta(days=N_DAYS)).isoformat()

COLS = "run_date, symbol, total_score, quality_score, growth_score, valuation_label, valuation_adj"
HDR  = f"  {'date':12} {'sym':8} {'tot':>5} {'Q':>5} {'G':>5} {'label':14} {'adj':>7}"
SEP  = "  " + "-" * 62


def run(con: sqlite3.Connection, sql: str, params: tuple) -> list:
    return con.execute(sql, params).fetchall()


def print_section(title: str, rows: list) -> None:
    print(f"\n{title}")
    print(SEP)
    print(HDR)
    print(SEP)
    if not rows:
        print("  (no results)")
    for r in rows:
        rd, sym, tot, q, g, label, adj = r
        adj_s = f"{adj:+.2f}" if adj is not None else "  n/a"
        print(f"  {rd:12} {sym:8} {tot:>5.1f} {q:>5.1f} {g:>5.1f} {label:14} {adj_s:>7}")
    print()


with sqlite3.connect(DB) as con:
    print(f"DB: {DB.resolve()}")
    print(f"Lookback: {N_DAYS} days  (from {cutoff})")

    # 1) deep_discount + high score
    rows1 = run(con, f"""
        SELECT {COLS} FROM daily_picks
        WHERE run_date >= ? AND valuation_label = 'deep_discount' AND total_score >= ?
        ORDER BY run_date DESC, total_score DESC
    """, (cutoff, MIN_HIGH_SCORE))
    print_section(f"1) deep_discount + high score  (total >= {MIN_HIGH_SCORE})", rows1)

    # 2) premium / expensive + high score
    rows2 = run(con, f"""
        SELECT {COLS} FROM daily_picks
        WHERE run_date >= ? AND valuation_label IN ('premium', 'expensive') AND total_score >= ?
        ORDER BY run_date DESC, total_score DESC
    """, (cutoff, MIN_HIGH_SCORE))
    print_section(f"2) premium/expensive + high score  (total >= {MIN_HIGH_SCORE})", rows2)

    # 3) deep_discount + mid Quality/Growth
    rows3 = run(con, f"""
        SELECT {COLS} FROM daily_picks
        WHERE run_date >= ?
          AND valuation_label = 'deep_discount'
          AND quality_score BETWEEN 60 AND 80
          AND growth_score  BETWEEN 60 AND 80
        ORDER BY run_date DESC, total_score DESC
    """, (cutoff,))
    print_section("3) deep_discount + mid Q/G  (quality 60–80, growth 60–80)", rows3)
