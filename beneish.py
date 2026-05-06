"""Beneish M-Score (8-variable model).

Threshold: M > -1.78 → likely earnings manipulator (hard gate).

Requires two consecutive annual periods of income-statement, balance-sheet,
and cash-flow data.  Returns None for m_score when data is insufficient
(< 2 periods for any required statement) so the gate is silently skipped.
"""
from __future__ import annotations

from typing import Any


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def compute(
    inc_rows: list[dict[str, Any]],
    bs_rows: list[dict[str, Any]],
    cf_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return {"m_score": float | None, "components": dict}.

    Rows are expected newest-first (FMP default order).
    t  = index 0 (current year)
    t1 = index 1 (prior year)
    """
    if len(inc_rows) < 2 or len(bs_rows) < 2 or len(cf_rows) < 2:
        return {"m_score": None, "components": {}}

    inc_t, inc_t1 = inc_rows[0], inc_rows[1]
    bs_t, bs_t1 = bs_rows[0], bs_rows[1]
    cf_t, cf_t1 = cf_rows[0], cf_rows[1]

    # ── raw fields ──────────────────────────────────────────────────────────
    rev_t   = inc_t.get("revenue")
    rev_t1  = inc_t1.get("revenue")
    gp_t    = inc_t.get("grossProfit")
    gp_t1   = inc_t1.get("grossProfit")
    sga_t   = inc_t.get("sellingGeneralAndAdministrativeExpenses")
    sga_t1  = inc_t1.get("sellingGeneralAndAdministrativeExpenses")
    ni_t    = inc_t.get("netIncome")

    rec_t   = bs_t.get("netReceivables")
    rec_t1  = bs_t1.get("netReceivables")
    ca_t    = bs_t.get("totalCurrentAssets")
    ca_t1   = bs_t1.get("totalCurrentAssets")
    ppe_t   = bs_t.get("propertyPlantEquipmentNet")
    ppe_t1  = bs_t1.get("propertyPlantEquipmentNet")
    ta_t    = bs_t.get("totalAssets")
    ta_t1   = bs_t1.get("totalAssets")
    ltd_t   = bs_t.get("longTermDebt") or 0.0
    ltd_t1  = bs_t1.get("longTermDebt") or 0.0
    cl_t    = bs_t.get("totalCurrentLiabilities")
    cl_t1   = bs_t1.get("totalCurrentLiabilities")

    dep_t   = cf_t.get("depreciationAndAmortization")
    dep_t1  = cf_t1.get("depreciationAndAmortization")
    cfo_t   = cf_t.get("operatingCashFlow")

    # ── index calculations ───────────────────────────────────────────────────
    # DSRI: Days Sales in Receivables Index
    dsri = _safe_div(
        _safe_div(rec_t, rev_t),
        _safe_div(rec_t1, rev_t1),
    )

    # GMI: Gross Margin Index  (prior / current; >1 = margin deterioration)
    gm_t  = _safe_div(gp_t, rev_t)
    gm_t1 = _safe_div(gp_t1, rev_t1)
    gmi = _safe_div(gm_t1, gm_t)

    # AQI: Asset Quality Index
    def _noncurrent_ratio(ca, ppe, ta):
        if ca is None or ppe is None or ta is None or ta == 0:
            return None
        return 1.0 - (ca + ppe) / ta

    aqi = _safe_div(_noncurrent_ratio(ca_t1, ppe_t1, ta_t1),
                    _noncurrent_ratio(ca_t, ppe_t, ta_t))

    # SGI: Sales Growth Index
    sgi = _safe_div(rev_t, rev_t1)

    # DEPI: Depreciation Index
    def _dep_rate(dep, ppe):
        if dep is None or ppe is None or (ppe + dep) == 0:
            return None
        return dep / (ppe + dep)

    depi = _safe_div(_dep_rate(dep_t1, ppe_t1), _dep_rate(dep_t, ppe_t))

    # SGAI: SGA Index
    sgai = _safe_div(
        _safe_div(sga_t, rev_t),
        _safe_div(sga_t1, rev_t1),
    )

    # ACCRUALS: Total Accruals to Total Assets
    accruals = _safe_div(
        (ni_t - cfo_t) if (ni_t is not None and cfo_t is not None) else None,
        ta_t,
    )

    # LVGI: Leverage Index
    def _lev_ratio(ltd, cl, ta):
        if cl is None or ta is None or ta == 0:
            return None
        return (ltd + cl) / ta

    lvgi = _safe_div(
        _lev_ratio(ltd_t, cl_t, ta_t),
        _lev_ratio(ltd_t1, cl_t1, ta_t1),
    )

    components = {
        "dsri": dsri, "gmi": gmi, "aqi": aqi, "sgi": sgi,
        "depi": depi, "sgai": sgai, "accruals": accruals, "lvgi": lvgi,
    }

    # Any required component missing → cannot compute score
    required = [dsri, gmi, aqi, sgi, accruals]
    if any(v is None for v in required):
        return {"m_score": None, "components": components}

    m = (
        -4.84
        + 0.920  * dsri
        + 0.528  * gmi
        + 0.404  * (aqi or 0.0)
        + 0.892  * sgi
        + 0.115  * (depi or 0.0)
        - 0.172  * (sgai or 0.0)
        + 4.679  * accruals
        - 0.327  * (lvgi or 0.0)
    )

    return {"m_score": round(m, 4), "components": components}
