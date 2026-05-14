"""Per-ticker factor extraction. Pulls only the fields needed for screening + scoring.

Returns the 8 frozen metrics, historical_years_available, raw fields required
by per-ticker hard rules (revenue, netIncome, operatingCashFlow), and shadow
factors for Phase 3 (Growth + Value/Risk) that are stored but not yet scored.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import TIMEZONE
from data.fetcher import FMPClient, FMPError
import piotroski

# ── Local FMP response cache (keyed by symbol, scoped to one calendar day) ───
_CACHE_DIR  = Path(__file__).parent / "data"
_CACHE_LOCK = threading.Lock()
_cache_today: str = ""
_cache_data:  dict = {}


def _cache_path(today: str) -> Path:
    return _CACHE_DIR / f"fmp_cache_{today}.json"


def _load_day(today: str) -> None:
    """Read today's cache file into _cache_data. Must be called with _CACHE_LOCK held."""
    global _cache_today, _cache_data
    if _cache_today == today:
        return
    p = _cache_path(today)
    _cache_data  = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    _cache_today = today


def _get_cached(symbol: str, today: str) -> dict | None:
    with _CACHE_LOCK:
        _load_day(today)
        return _cache_data.get(symbol)


def _put_cached(symbol: str, raw: dict, today: str) -> None:
    with _CACHE_LOCK:
        _load_day(today)
        _cache_data[symbol] = raw
        _cache_path(today).write_text(
            json.dumps(_cache_data, separators=(",", ":")),
            encoding="utf-8",
        )


METRIC_NAMES = [
    "returnOnEquity",
    "returnOnAssets",
    "grossProfitMargin",
    "operatingProfitMargin",
    "operatingCashFlowToNetIncome",
    "revenueGrowth",
    "debtToEquityRatio",
    "priceEarningsRatio",
]


def _cagr(start: Any, end: Any, n: int) -> float | None:
    """Compound annual growth rate from start to end over n years.
    Returns None when either value is non-positive, or n < 1.
    """
    try:
        s, e = float(start), float(end)
    except (TypeError, ValueError):
        return None
    if n < 1 or s <= 0 or e <= 0:
        return None
    return round((e / s) ** (1 / n) - 1, 6)


def _row_fcf(row: dict[str, Any]) -> float:
    """Free cash flow from a cash-flow row. Capex is negative in FMP convention."""
    return (row.get("operatingCashFlow") or 0) + (row.get("capitalExpenditure") or 0)


def _pick(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def classify_history(years: int) -> str:
    if years < 5:
        return "reject"
    if years < 10:
        return "acceptable"
    return "preferred"


def extract(symbol: str, client: FMPClient | None = None,
            years: int = 10) -> dict[str, Any]:
    """Fetch all data needed for screening + scoring for one ticker.

    Returns a dict with: symbol, fiscalYear, historical_years_available,
    history_class, latest revenue/netIncome/operatingCashFlow, the 8 metrics,
    and raw multi-year rows (_inc_rows, _bs_rows, _cf_rows) for Beneish.
    Raises FMPError on fetch failure.
    """
    today  = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    cached = _get_cached(symbol, today)
    if cached is not None:
        inc = cached["inc"]
        bs  = cached["bs"]
        cf  = cached["cf"]
        r   = cached["r"]
        km  = cached["km"]
        g   = cached["g"]
    else:
        c   = client or FMPClient()
        inc = c.income_statement(symbol, years=years) or []
        bs  = c.balance_sheet(symbol, years=years)    or []
        cf  = c.cash_flow(symbol, years=years)        or []
        r   = c.ratios(symbol, years=years)           or []
        km  = c.key_metrics(symbol, years=years)      or []
        g   = c.financial_growth(symbol, years=years) or []
        _put_cached(symbol, {"inc": inc, "bs": bs, "cf": cf,
                             "r": r, "km": km, "g": g}, today)

    inc0 = inc[0] if inc else {}
    bs0  = bs[0] if bs else {}
    cf0 = cf[0] if cf else {}
    r0 = r[0] if r else {}
    km0 = km[0] if km else {}
    g0 = g[0] if g else {}

    rev = inc0.get("revenue")
    ni = inc0.get("netIncome")
    ocf = cf0.get("operatingCashFlow")
    ocf_ni = (ocf / ni) if (ocf is not None and ni and ni > 0) else None

    history_count = len(inc)

    # ── Phase 3.2 Growth shadow factors ─────────────────────────────────────
    # Years spanned: up to 5, bounded by available rows (screener guarantees ≥5).
    _n     = min(5, len(inc) - 1)
    _n_cf  = min(5, len(cf)  - 1)

    revenue_cagr_5y = _cagr(
        inc[_n].get("revenue") if _n > 0 else None,
        inc0.get("revenue"), _n,
    )
    _eps0 = inc0.get("eps") or inc0.get("epsDiluted")
    _epsN = (inc[_n].get("eps") or inc[_n].get("epsDiluted")) if _n > 0 else None
    eps_cagr_5y = _cagr(_epsN, _eps0, _n)

    fcf_cagr_5y = (
        _cagr(_row_fcf(cf[_n_cf]), _row_fcf(cf0), _n_cf)
        if _n_cf > 0 else None
    )
    asset_growth = g0.get("assetGrowth")   # 1-year YoY; used as penalty in scoring

    # ── Phase 3.3 Value/Risk shadow factors ──────────────────────────────────
    ev_ebitda = km0.get("evToEBITDA")
    ps_ratio  = r0.get("priceToSalesRatio")
    peg_ratio = r0.get("priceToEarningsGrowthRatio")

    # PE vs own history: current PE / median of prior years' PE.
    # Require ≥3 positive historical PEs to produce a stable median.
    # Value < 1 = cheaper than own history; > 1 = pricier than history.
    _pe_cur  = r0.get("priceToEarningsRatio")
    _pe_hist = [
        float(row["priceToEarningsRatio"])
        for row in r[1:]
        if row.get("priceToEarningsRatio")
        and float(row.get("priceToEarningsRatio", 0) or 0) > 0
    ]
    if len(_pe_hist) >= 3 and _pe_cur and float(_pe_cur or 0) > 0:
        _med = sorted(_pe_hist)[len(_pe_hist) // 2]
        pe_vs_own_history = round(float(_pe_cur) / _med, 4) if _med else None
    else:
        pe_vs_own_history = None

    return {
        "symbol": symbol,
        "fiscalYear": inc0.get("fiscalYear") or r0.get("fiscalYear"),
        "historical_years_available": history_count,
        "history_class": classify_history(history_count),
        "revenue": rev,
        "netIncome": ni,
        "operatingCashFlow": ocf,
        # 8 frozen metrics
        "returnOnEquity": _pick(r0, "returnOnEquity") or _pick(km0, "returnOnEquity"),
        "returnOnAssets": _pick(r0, "returnOnAssets") or _pick(km0, "returnOnAssets"),
        "grossProfitMargin": _pick(r0, "grossProfitMargin"),
        "operatingProfitMargin": _pick(r0, "operatingProfitMargin"),
        "operatingCashFlowToNetIncome": ocf_ni,
        "revenueGrowth": _pick(g0, "revenueGrowth"),
        "debtToEquityRatio": _pick(r0, "debtToEquityRatio"),
        "priceEarningsRatio": _pick(
            r0, "priceToEarningsRatio", "priceEarningsRatio", "peRatio"
        ),
        # raw multi-year rows for Beneish M-Score (newest-first)
        "_inc_rows": inc,
        "_bs_rows": bs,
        "_cf_rows": cf,
        # Piotroski F-Score (Phase 3 Quality)
        "f_score": (
            piotroski.f_score(
                piotroski.compute_f_signals(inc[0], inc[1], bs[0], bs[1], cf[0])
            )
            if len(inc) >= 2 and len(bs) >= 2 and cf
            else None
        ),
        # Novy-Marx gross profitability (Phase 3 Quality)
        "novy_marx_gp_assets": (
            (inc0.get("grossProfit") / bs0["totalAssets"])
            if (inc0.get("grossProfit") is not None
                and bs0.get("totalAssets"))
            else None
        ),
        # Phase 3.2 — Growth shadow factors (stored; not yet in scoring)
        "revenue_cagr_5y": revenue_cagr_5y,
        "eps_cagr_5y":     eps_cagr_5y,
        "fcf_cagr_5y":     fcf_cagr_5y,
        "asset_growth":    asset_growth,
        # Phase 3.3 — Value/Risk shadow factors (stored; not yet in scoring)
        "ev_ebitda":          ev_ebitda,
        "ps_ratio":           ps_ratio,
        "peg_ratio":          peg_ratio,
        "pe_vs_own_history":  pe_vs_own_history,
    }
