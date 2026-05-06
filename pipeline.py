"""End-to-end pipeline: universe -> screen -> score -> rank -> cooldown -> store."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

from config import CACHE_DB, COOLDOWN_DAYS, TOP_N, VALUATION_WEIGHT
from cooldown import apply_cooldown
from data import storage
from data.fetcher import FMPClient
from scoring import SCORING_VERSION, WEIGHTS_V2, score_cross_sectional
from screener import screen_ticker
from valuation import apply_valuation
import universe

log = logging.getLogger(__name__)

RAW_TOP = 20
MAX_WORKERS = 6
_MAX_WORKERS_CAP = 20


def _short_reason(s: dict[str, Any]) -> str:
    return (
        f"Q={s['quality_score']:.0f} G={s['growth_score']:.0f} "
        f"VR={s['value_risk_score']:.0f}; +{s['top_2_drivers'][0]} "
        f"-{s['bottom_2_drivers'][0]}"
    )[:120]


def _screen_only(uni_row: dict[str, Any], client: FMPClient) -> dict[str, Any]:
    """Pass 1 worker: fetch + screen; returns raw factors only (no scoring)."""
    sym = uni_row["symbol"]
    s = screen_ticker(sym, client)
    if not s["pass"]:
        return {"pass": False, "symbol": sym, "reason": s["reason"]}
    return {
        "pass": True,
        "symbol": sym,
        "company_name": uni_row.get("companyName"),
        "factors": s["factors"],
    }


def _build_row(c: dict[str, Any], run_date: str, rank: int) -> dict[str, Any]:
    sc    = c["scoring"]
    sc_v1 = c.get("scoring_v1") or {}
    f     = c["factors"]
    return {
        "run_date": run_date,
        "symbol": c["symbol"],
        "company_name": c.get("company_name"),
        "total_score": sc["total_score"],
        "quality_score": sc["quality_score"],
        "growth_score": sc["growth_score"],
        "value_risk_score": sc["value_risk_score"],
        "recommendation_rank": rank,
        "is_daily_pick": c.get("is_daily_pick", 0),
        "eligible_for_pick": c.get("eligible_for_pick", 1),
        "in_cooldown": c.get("in_cooldown", 0),
        "cooldown_until": c.get("cooldown_until"),
        "historical_years_available": f["historical_years_available"],
        "top_drivers": ",".join(sc["top_2_drivers"]),
        "bottom_drivers": ",".join(sc["bottom_2_drivers"]),
        "short_reason": _short_reason(sc),
        # valuation overlay (shadow; not used for ranking)
        "sector_median_pe":       c.get("sector_median_pe"),
        "fair_value_pe":          c.get("fair_value_pe"),
        "pe_vs_sector":           c.get("pe_vs_sector"),
        "valuation_adj":          c.get("valuation_adj", 0.0),
        "valuation_label":        c.get("valuation_label", "n/a"),
        "valuation_model_version": c.get("valuation_model_version", "v1_static_sector_pe"),
        # dual ranking (observation only; does not affect daily pick selection)
        "total_score_adj":                    c.get("total_score_adj"),
        "recommendation_rank_with_valuation": c.get("recommendation_rank_with_valuation"),
        # Beneish M-Score (Phase 2)
        "m_score":      f.get("m_score"),
        "beneish_flag": f.get("beneish_flag"),
        # Piotroski F-Score + Novy-Marx GP/Assets (Phase 3 Quality, shadow)
        "f_score":             f.get("f_score"),
        "novy_marx_gp_assets": f.get("novy_marx_gp_assets"),
        # Growth shadow factors (Phase 3.2)
        "revenue_cagr_5y": f.get("revenue_cagr_5y"),
        "eps_cagr_5y":     f.get("eps_cagr_5y"),
        "fcf_cagr_5y":     f.get("fcf_cagr_5y"),
        "asset_growth":    f.get("asset_growth"),
        # Value/Risk shadow factors (Phase 3.3)
        "ev_ebitda":          f.get("ev_ebitda"),
        "ps_ratio":           f.get("ps_ratio"),
        "peg_ratio":          f.get("peg_ratio"),
        "pe_vs_own_history":  f.get("pe_vs_own_history"),
        # Phase 4 diagnostics: V1 linear scores + metadata
        "total_score_v1":       sc_v1.get("total_score"),
        "quality_score_v1":     sc_v1.get("quality_score"),
        "growth_score_v1":      sc_v1.get("growth_score"),
        "value_risk_score_v1":  sc_v1.get("value_risk_score"),
        "normalization_method":  SCORING_VERSION,
        "universe_n_at_scoring": sc.get("universe_n"),
        # Phase 6 performance tracking (non-nil only for the daily pick)
        "pick_price": c.get("pick_price"),
    }


def run(
    today: date | None = None,
    top_n: int = TOP_N,
    db_path: Path = CACHE_DB,
    max_workers: int = MAX_WORKERS,
    persist: bool = True,
) -> dict[str, Any]:
    max_workers = min(max_workers, _MAX_WORKERS_CAP)
    today = today or date.today()
    run_date = today.isoformat()
    t0 = time.monotonic()
    stage_t: dict[str, float] = {}

    # Init DB upfront so cooldown_map can query even when persist=False.
    storage.init_db(db_path)

    log.info("[1/7] building universe...")
    _ts = time.monotonic()
    uni = universe.build_universe()
    eligible = uni["eligible"]
    stage_t["universe"] = round(time.monotonic() - _ts, 1)
    log.info("    eligible universe: %d  (%.1fs)", len(eligible), stage_t["universe"])

    log.info("[2/7] per-ticker screen (workers=%d)...", max_workers)
    client = FMPClient()
    candidates: list[dict[str, Any]] = []
    rejects: dict[str, int] = {}
    err_samples: list[str] = []
    done = 0
    _ts = time.monotonic()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_screen_only, row, client): row["symbol"]
                for row in eligible}
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception as e:
                rejects["FETCH_ERROR"] = rejects.get("FETCH_ERROR", 0) + 1
                if len(err_samples) < 5:
                    err_samples.append(f"{futs[fut]}: {type(e).__name__}: {str(e)[:80]}")
            else:
                if r["pass"]:
                    candidates.append(r)
                else:
                    rejects[r["reason"]] = rejects.get(r["reason"], 0) + 1
            done += 1
            if done % 200 == 0:
                log.info("    progress: %d/%d  passed=%d", done, len(eligible), len(candidates))
    stage_t["screen"] = round(time.monotonic() - _ts, 1)
    log.info("    passed=%d  rejects=%s  (%.1fs)", len(candidates), rejects, stage_t["screen"])
    for s in err_samples:
        log.info("    fetch_err sample: %s", s)

    log.info("[2b/7] cross-sectional z-score scoring (n=%d, %s)...",
             len(candidates), SCORING_VERSION)
    _ts = time.monotonic()
    candidates = score_cross_sectional(candidates)
    stage_t["score"] = round(time.monotonic() - _ts, 1)
    log.info("    scored=%d  weights Q=%.0f%% G=%.0f%% V=%.0f%%  (%.1fs)",
             len(candidates),
             WEIGHTS_V2["quality"]    * 100,
             WEIGHTS_V2["growth"]     * 100,
             WEIGHTS_V2["value_risk"] * 100,
             stage_t["score"])

    log.info("[3/7] ranking by total_score...")
    candidates.sort(key=lambda c: c["scoring"]["total_score"], reverse=True)
    raw_top = candidates[:RAW_TOP]
    for i, c in enumerate(raw_top, start=1):
        c["recommendation_rank"] = i

    log.info("[3b/7] fetching sector for top-%d (valuation overlay)...", RAW_TOP)
    _ts = time.monotonic()
    for c in raw_top:
        try:
            prof = client.profile(c["symbol"])
            c["sector"] = prof.get("sector")
        except Exception:
            c["sector"] = None

    log.info("[3c/7] applying valuation overlay...")
    for c in raw_top:
        apply_valuation(c)

    log.info("[3d/7] computing valuation-adjusted ranking (k=%.2f)...", VALUATION_WEIGHT)
    for c in raw_top:
        adj = c.get("valuation_adj") or 0.0   # treat NULL / n/a sentinel as 0.0
        c["total_score_adj"] = round(
            c["scoring"]["total_score"] + VALUATION_WEIGHT * adj, 2
        )
    adj_sorted = sorted(raw_top, key=lambda c: c["total_score_adj"], reverse=True)
    adj_rank_map = {c["symbol"]: i for i, c in enumerate(adj_sorted, start=1)}
    for c in raw_top:
        c["recommendation_rank_with_valuation"] = adj_rank_map[c["symbol"]]
    stage_t["valuation"] = round(time.monotonic() - _ts, 1)
    log.info("    rank shifts (orig->adj): %s  (%.1fs)",
             " ".join(
                 f"{c['symbol']}:{c['recommendation_rank']}->{c['recommendation_rank_with_valuation']}"
                 for c in raw_top
                 if c["recommendation_rank"] != c["recommendation_rank_with_valuation"]
             ) or "none",
             stage_t["valuation"])

    log.info("[4/7] applying %d-day cooldown...", COOLDOWN_DAYS)
    _ts = time.monotonic()
    walk_input = [{"symbol": c["symbol"], "recommendation_rank": c["recommendation_rank"]}
                  for c in raw_top]
    apply_cooldown(walk_input, today=today, db_path=db_path)
    cd_by_sym = {x["symbol"]: x for x in walk_input}
    for c in raw_top:
        meta = cd_by_sym[c["symbol"]]
        c["in_cooldown"] = meta["in_cooldown"]
        c["eligible_for_pick"] = meta["eligible_for_pick"]
        c["cooldown_until"] = meta["cooldown_until"]
        c["is_daily_pick"] = meta["is_daily_pick"]
    stage_t["cooldown"] = round(time.monotonic() - _ts, 1)

    daily_pick = next((c for c in raw_top if c["is_daily_pick"] == 1), None)
    log.info("    daily_pick=%s rank=%s  in_cooldown=%d  (%.1fs)",
             daily_pick["symbol"] if daily_pick else None,
             daily_pick["recommendation_rank"] if daily_pick else None,
             sum(1 for c in raw_top if c.get("in_cooldown")),
             stage_t["cooldown"])

    log.info("[4b/7] fetching EOD close price for daily pick (phase 6)...")
    if daily_pick:
        try:
            hist = client.historical_price(daily_pick["symbol"], light=False)
            daily_pick["pick_price"] = hist[0]["close"] if hist else None
            log.info("    pick_price %s = %s", daily_pick["symbol"],
                     f"{daily_pick['pick_price']:.4f}" if daily_pick["pick_price"] else "n/a")
        except Exception:
            log.warning("    could not fetch pick_price for %s", daily_pick["symbol"])
            daily_pick["pick_price"] = None

    log.info("[5/7] preparing top-%d storage rows...", top_n)
    _ts = time.monotonic()
    top_rows = [_build_row(c, run_date, c["recommendation_rank"])
                for c in raw_top[:top_n]]
    if daily_pick and daily_pick["recommendation_rank"] > top_n:
        top_rows.append(_build_row(daily_pick, run_date,
                                   daily_pick["recommendation_rank"]))
    val_overlaid = sum(1 for r in top_rows if r.get("valuation_label", "n/a") != "n/a")
    log.info("    valuation overlay: %d/%d stored rows have overlay data (model=%s)",
             val_overlaid, len(top_rows), "v1_static_sector_pe")

    if persist:
        log.info("[6/7] writing to %s ...", db_path)
        storage.init_db(db_path)
        storage.insert_picks(top_rows, path=db_path)
    stage_t["persist"] = round(time.monotonic() - _ts, 1)

    elapsed = round(time.monotonic() - t0, 1)
    log.info("[7/7] done in %.1fs  stages: universe=%.1fs screen=%.1fs "
             "score=%.1fs valuation=%.1fs cooldown=%.1fs persist=%.1fs",
             elapsed,
             stage_t.get("universe", 0), stage_t.get("screen", 0),
             stage_t.get("score", 0),
             stage_t.get("valuation", 0), stage_t.get("cooldown", 0),
             stage_t.get("persist", 0))

    return {
        "run_date": run_date,
        "elapsed_s": elapsed,
        "universe_counts": {
            "raw_total": uni["raw_total"],
            "by_exchange": uni["by_exchange"],
            "dropped_symbol_filter": uni["dropped_symbol_filter"],
            "dropped_sector": uni["dropped_sector"],
            "dropped_adr": uni["dropped_adr"],
            "dropped_dollar_volume": uni["dropped_dollar_volume"],
            "eligible": uni["eligible_count"],
        },
        "scored": len(candidates),
        "rejects": rejects,
        "raw_top": raw_top,
        "daily_picks_rows": top_rows,
        "daily_pick": daily_pick,
        "stage_timings": stage_t,
    }
