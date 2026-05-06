"""60-day cooldown: walk ranked candidates and pick first eligible.

Stamps cooldown fields on every input row and selects exactly one daily pick.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from config import CACHE_DB, COOLDOWN_DAYS
from data import storage


def apply_cooldown(
    ranked: list[dict[str, Any]],
    today: date,
    cooldown_days: int = COOLDOWN_DAYS,
    db_path: Path = CACHE_DB,
) -> list[dict[str, Any]]:
    """Annotate each ranked candidate with cooldown fields, choose daily pick.

    Args:
        ranked: list of dicts (already sorted by total_score desc), must contain
                'symbol' and 'recommendation_rank'.
        today: run date (MYT) used for cooldown calculation.
        cooldown_days: lookback window.
        db_path: SQLite path with prior daily_picks.

    Returns:
        Same list, in-place updated, with these fields set per row:
        in_cooldown, eligible_for_pick, cooldown_until, is_daily_pick.
        Exactly zero or one row will have is_daily_pick=1.
    """
    cd_map = storage.cooldown_map(today, cooldown_days, db_path)

    daily_pick_set = False
    for row in ranked:
        sym = row["symbol"]
        in_cd = sym in cd_map
        row["in_cooldown"] = 1 if in_cd else 0
        row["eligible_for_pick"] = 0 if in_cd else 1
        row["cooldown_until"] = cd_map.get(sym)
        if not daily_pick_set and not in_cd:
            row["is_daily_pick"] = 1
            daily_pick_set = True
        else:
            row["is_daily_pick"] = 0

    return ranked
