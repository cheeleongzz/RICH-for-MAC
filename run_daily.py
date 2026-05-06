"""Manual daily entrypoint. Scheduler is intentionally NOT installed yet.

Run by hand 2-3 times across different days/time windows to observe FETCH_ERROR
stability (target <10%). Only after stability is confirmed do we wire Task
Scheduler. Each run appends one row to logs/run_metrics.csv for audit.

Usage:
    py run_daily.py
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from config import TIMEZONE
from logging_utils import append_run_metrics, setup_logging
from pipeline import run


def main() -> int:
    setup_logging()
    today = datetime.now(ZoneInfo(TIMEZONE)).date()
    log = logging.getLogger("run_daily")
    log.info("=== RICH manual run %s (MYT) ===", today.isoformat())
    try:
        result = run(today=today)
    except Exception:
        log.exception("pipeline failed")
        return 1

    csv_path = append_run_metrics(result)
    pick = result.get("daily_pick")
    log.info("daily pick: %s  metrics appended to %s",
             pick["symbol"] if pick else "<none>", csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
