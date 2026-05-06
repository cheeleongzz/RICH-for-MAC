"""Piotroski F-Score (9-signal model).

F-score ∈ [0,9]; higher = stronger financial position.
Requires two consecutive annual IS, BS, and CF rows (newest-first).
Individual signals default to 0 when source fields are missing.
"""
from __future__ import annotations

from typing import Any


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def compute_f_signals(
    inc0: dict[str, Any],
    inc1: dict[str, Any],
    bs0: dict[str, Any],
    bs1: dict[str, Any],
    cf0: dict[str, Any],
) -> dict[str, int]:
    """Return dict of 9 binary Piotroski signals (0 or 1).

    inc0/inc1 = income statement current/prior year.
    bs0/bs1   = balance sheet current/prior year.
    cf0       = cash flow current year.
    Missing source fields cause the affected signal to be scored 0 (conservative).
    """
    ni0  = inc0.get("netIncome")
    ni1  = inc1.get("netIncome")
    rev0 = inc0.get("revenue")
    rev1 = inc1.get("revenue")
    gp0  = inc0.get("grossProfit")
    gp1  = inc1.get("grossProfit")
    shs0 = inc0.get("weightedAverageShsOut")
    shs1 = inc1.get("weightedAverageShsOut")

    ta0  = bs0.get("totalAssets")
    ta1  = bs1.get("totalAssets")
    ltd0 = bs0.get("longTermDebt") or 0.0
    ltd1 = bs1.get("longTermDebt") or 0.0
    ca0  = bs0.get("totalCurrentAssets")
    ca1  = bs1.get("totalCurrentAssets")
    cl0  = bs0.get("totalCurrentLiabilities")
    cl1  = bs1.get("totalCurrentLiabilities")

    ocf0 = cf0.get("operatingCashFlow")

    roa0       = _safe_div(ni0, ta0)
    roa1       = _safe_div(ni1, ta1)
    cfo_over_a = _safe_div(ocf0, ta0)

    # ── Profitability ────────────────────────────────────────────────────────
    # F1: Return on assets positive
    f1 = 1 if (roa0 is not None and roa0 > 0) else 0
    # F2: Operating cash flow positive
    f2 = 1 if (ocf0 is not None and ocf0 > 0) else 0
    # F3: ROA improved year-over-year
    f3 = 1 if (roa0 is not None and roa1 is not None and roa0 > roa1) else 0
    # F4: Cash earnings quality (CFO/assets > ROA)
    f4 = 1 if (cfo_over_a is not None and roa0 is not None and cfo_over_a > roa0) else 0

    # ── Leverage / Liquidity / Dilution ──────────────────────────────────────
    # F5: Long-term leverage ratio decreased
    lev0 = _safe_div(ltd0, ta0)
    lev1 = _safe_div(ltd1, ta1)
    f5 = 1 if (lev0 is not None and lev1 is not None and lev0 < lev1) else 0

    # F6: Current ratio improved
    cr0 = _safe_div(ca0, cl0)
    cr1 = _safe_div(ca1, cl1)
    f6 = 1 if (cr0 is not None and cr1 is not None and cr0 > cr1) else 0

    # F7: No share dilution (shares outstanding did not increase)
    f7 = 1 if (shs0 is not None and shs1 is not None and shs0 <= shs1) else 0

    # ── Operating Efficiency ─────────────────────────────────────────────────
    # F8: Gross margin improved
    gm0 = _safe_div(gp0, rev0)
    gm1 = _safe_div(gp1, rev1)
    f8 = 1 if (gm0 is not None and gm1 is not None and gm0 > gm1) else 0

    # F9: Asset turnover improved
    at0 = _safe_div(rev0, ta0)
    at1 = _safe_div(rev1, ta1)
    f9 = 1 if (at0 is not None and at1 is not None and at0 > at1) else 0

    return {"f1": f1, "f2": f2, "f3": f3, "f4": f4,
            "f5": f5, "f6": f6, "f7": f7, "f8": f8, "f9": f9}


def f_score(signals: dict[str, int]) -> int:
    """Sum all 9 signals → int in [0, 9]."""
    return sum(signals.values())
