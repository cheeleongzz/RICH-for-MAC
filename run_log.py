"""Append run metrics to CSV for stability monitoring before scheduler."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import LOG_DIR, TIMEZONE


def append_run_metrics(result: dict) -> Path:
    """Log one run to logs/run_metrics.csv. Returns path."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = LOG_DIR / "run_metrics.csv"

    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    rejects = result.get("rejects") or {}
    scored = result.get("scored") or 0
    universe_eligible = result.get("universe_counts", {}).get("eligible") or 0
    total_screened = scored + sum(rejects.values())
    fetch_err = rejects.get("FETCH_ERROR", 0)
    fetch_err_pct = round(100.0 * fetch_err / total_screened, 1) if total_screened else 0

    pick = result.get("daily_pick")
    pick_sym = pick["symbol"] if pick else "-"

    row = {
        "run_datetime": now.isoformat(),
        "run_date": now.date().isoformat(),
        "run_time_my": now.strftime("%H:%M:%S"),
        "elapsed_s": result.get("elapsed_s") or 0,
        "universe_eligible": universe_eligible,
        "total_screened": total_screened,
        "scored": scored,
        "FETCH_ERROR": fetch_err,
        "MISSING_FIELDS": rejects.get("MISSING_FIELDS", 0),
        "NI_OCF_NONPOSITIVE": rejects.get("NI_OCF_NONPOSITIVE", 0),
        "HIST_LT_5": rejects.get("HIST_LT_5", 0),
        "REV_NONPOSITIVE": rejects.get("REV_NONPOSITIVE", 0),
        "fetch_error_pct": fetch_err_pct,
        "daily_pick": pick_sym,
    }

    exists = csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=row.keys())
        if not exists:
            w.writeheader()
        w.writerow(row)

    return csv_path
