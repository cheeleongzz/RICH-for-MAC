"""Show which stocks changed rank due to valuation_adj.

Positive shift = stock moved UP in ranking  (e.g. rank 5 -> rank 2 = +3)
Negative shift = stock moved DOWN in ranking (e.g. rank 2 -> rank 5 = -3)

Usage:
    py rank_shift_reviewer.py                    # today (MYT)
    py rank_shift_reviewer.py --date 2026-04-27
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DB = Path(__file__).parent / "data" / "cache.db"
TZ = ZoneInfo("Asia/Kuala_Lumpur")

COLS = (
    "symbol", "company_name",
    "recommendation_rank", "recommendation_rank_with_valuation",
    "total_score", "total_score_adj",
    "valuation_label", "valuation_adj",
    "quality_score", "growth_score", "value_risk_score",
)


def _f(v, fmt=".1f") -> str:
    try:
        return format(float(v), fmt) if v is not None else "n/a"
    except (TypeError, ValueError):
        return "n/a"


def _signed(v) -> str:
    try:
        return f"{float(v):+.2f}" if v is not None else "n/a"
    except (TypeError, ValueError):
        return "n/a"


def fetch(run_date: str) -> list[dict]:
    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        return [
            dict(r) for r in con.execute(
                f"SELECT {', '.join(COLS)} FROM daily_picks "
                "WHERE run_date = ? ORDER BY recommendation_rank",
                (run_date,),
            ).fetchall()
        ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    target = args.date or datetime.now(TZ).date().isoformat()

    if not DB.exists():
        print(f"[ERROR] DB not found: {DB}")
        return 1

    try:
        rows = fetch(target)
    except sqlite3.OperationalError as exc:
        print(f"[ERROR] DB query failed: {exc}")
        return 1

    if not rows:
        print(f"No data for {target}. Run `py run_daily.py` first.")
        return 1

    # Compute shifts; skip rows where either rank column is NULL
    shifted = []
    for r in rows:
        orig = r.get("recommendation_rank")
        adj  = r.get("recommendation_rank_with_valuation")
        if orig is None or adj is None:
            continue
        shift = orig - adj   # positive = moved up, negative = moved down
        if shift != 0:
            shifted.append({**r, "_shift": shift})

    total   = len(rows)
    n_shift = len(shifted)

    print()
    print(f"  date     : {target}")
    print(f"  rows     : {total}   rank shifts: {n_shift}")
    print(f"  note     : positive shift = stock moved UP  (orig rank > adj rank)")
    print(f"             negative shift = stock moved DOWN (orig rank < adj rank)")

    if not shifted:
        print("\n  No rank shifts for this date.")
        print()
        return 0

    # Sort: largest absolute shift first, then by original rank ascending
    shifted.sort(key=lambda r: (-abs(r["_shift"]), r["recommendation_rank"]))

    # Column widths
    W_SYM   = 6
    W_NAME  = 22
    W_NUM   = 5
    W_SCORE = 6
    W_LABEL = 14
    W_STAT  = 5

    hdr = (
        f"  {'sym':{W_SYM}}  {'company':{W_NAME}}  "
        f"{'orig':>{W_NUM}}  {'adj':>{W_NUM}}  {'shift':>{W_NUM}}  "
        f"{'score':>{W_SCORE}}  {'adj_sc':>{W_SCORE}}  "
        f"{'label':{W_LABEL}}  {'v_adj':>{W_STAT}}  "
        f"{'Q':>{W_STAT}}  {'G':>{W_STAT}}  {'VR':>{W_STAT}}"
    )
    sep = "  " + "-" * (len(hdr) - 2)

    print()
    print(hdr)
    print(sep)

    for r in shifted:
        shift    = r["_shift"]
        shift_s  = f"{shift:+d}"
        sym      = (r.get("symbol") or "")[:W_SYM]
        name     = (r.get("company_name") or "")[:W_NAME]
        orig     = r.get("recommendation_rank", "?")
        adj_rank = r.get("recommendation_rank_with_valuation", "?")
        label    = (r.get("valuation_label") or "n/a")[:W_LABEL]

        print(
            f"  {sym:{W_SYM}}  {name:{W_NAME}}  "
            f"{orig!s:>{W_NUM}}  {adj_rank!s:>{W_NUM}}  {shift_s:>{W_NUM}}  "
            f"{_f(r.get('total_score')):>{W_SCORE}}  "
            f"{_f(r.get('total_score_adj')):>{W_SCORE}}  "
            f"{label:{W_LABEL}}  "
            f"{_signed(r.get('valuation_adj')):>{W_STAT}}  "
            f"{_f(r.get('quality_score')):>{W_STAT}}  "
            f"{_f(r.get('growth_score')):>{W_STAT}}  "
            f"{_f(r.get('value_risk_score')):>{W_STAT}}"
        )

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
