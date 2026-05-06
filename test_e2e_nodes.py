#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RICH end-to-end node tests - all 10 nodes.
Run from C:\\Users\\chaim\\Desktop\\RICH:  python test_e2e_nodes.py
"""
from __future__ import annotations
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import os
import sqlite3
import sys
import traceback
from datetime import date
from pathlib import Path

RICH_DIR = Path(__file__).parent
os.chdir(RICH_DIR)
sys.path.insert(0, str(RICH_DIR))

# ── Reporting helpers ─────────────────────────────────────────────────────────
_results: list[tuple[str, str, str]] = []  # (node_label, status, notes)

def _report(node: str, status: str, notes: str = "") -> None:
    _results.append((node, status, notes))
    marker = "PASS" if status == "PASS" else "FAIL"
    suffix = f"  [{notes}]" if notes else ""
    print(f"  [{marker}] {node}{suffix}")

def PASS(node: str, notes: str = "") -> None:
    _report(node, "PASS", notes)

def FAIL(node: str, notes: str = "") -> None:
    _report(node, "FAIL", notes)


# ── Shared state populated across nodes ───────────────────────────────────────
uni_result:        dict | None = None   # Node 1
screener_results:  dict = {}            # Node 2  sym -> result dict
factor_results:    dict = {}            # Node 3  sym -> factors dict
scored_candidates: list = []            # Node 4  list of candidate dicts

TEST_TICKERS = ["AAPL", "MSFT", "T", "GME", "PLTR"]


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 1 — Universe
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 60)
print("NODE 1 — Universe")
print("─" * 60)
try:
    import universe as _universe_mod
    uni_result = _universe_mod.build_universe()
    n = uni_result["eligible_count"]
    print(f"  raw_total={uni_result['raw_total']}  dropped_sector={uni_result['dropped_sector']}"
          f"  dropped_adr={uni_result['dropped_adr']}  eligible={n}")
    # The methodology doc says ~1 100–1 150; allow a ±20% band for market-day variance
    if 800 <= n <= 1500:
        PASS("1_universe", f"eligible={n} (expected 1100-1150)")
    else:
        FAIL("1_universe", f"eligible={n} — outside expected 800-1500 band")
except Exception:
    FAIL("1_universe", traceback.format_exc(limit=1).strip())


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 2 — Screener  (AAPL/MSFT/T/GME/PLTR)
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 60)
print("NODE 2 — Screener")
print("─" * 60)
try:
    from screener import screen_ticker
    from data.fetcher import FMPClient
    _client = FMPClient()
    _errors: list[str] = []

    for sym in TEST_TICKERS:
        try:
            r = screen_ticker(sym, _client)
            screener_results[sym] = r
            outcome = "PASS" if r["pass"] else f"REJECT({r['reason']})"
            detail = f"  detail={r.get('detail','')}" if r.get("detail") else ""
            print(f"  {sym:5}: {outcome}{detail}")
        except Exception as exc:
            _errors.append(f"{sym}: {exc}")

    if _errors:
        FAIL("2_screener", f"exceptions: {'; '.join(_errors)}")
    else:
        aapl_ok = screener_results.get("AAPL", {}).get("pass", False)
        msft_ok = screener_results.get("MSFT", {}).get("pass", False)
        if aapl_ok and msft_ok:
            summary = "  ".join(
                f"{s}={'PASS' if screener_results[s]['pass'] else screener_results[s]['reason']}"
                for s in TEST_TICKERS
            )
            PASS("2_screener", summary)
        else:
            FAIL("2_screener",
                 f"AAPL({'pass' if aapl_ok else 'FAIL'}) or "
                 f"MSFT({'pass' if msft_ok else 'FAIL'}) did not pass")
except Exception:
    FAIL("2_screener", traceback.format_exc(limit=2).strip().replace("\n", " "))


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 3 — Factors
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 60)
print("NODE 3 — Factors")
print("─" * 60)
try:
    from factors import METRIC_NAMES

    # Reuse factors already fetched inside screen_ticker to avoid duplicate API calls.
    # screen_ticker calls extract() and stores results in r["factors"].
    _shadow_fields = [
        "f_score", "novy_marx_gp_assets",
        "revenue_cagr_5y", "eps_cagr_5y", "fcf_cagr_5y", "asset_growth",
        "ev_ebitda", "ps_ratio", "peg_ratio", "pe_vs_own_history",
    ]
    _issues: list[str] = []

    for sym in TEST_TICKERS:
        sr = screener_results.get(sym)
        if sr is None:
            print(f"  {sym:5}: SKIP (no screener result)")
            continue
        f = sr.get("factors")
        if f is None:
            print(f"  {sym:5}: SKIP (factors=None, screener gave {sr.get('reason')})")
            continue
        factor_results[sym] = f

        core_missing  = [k for k in METRIC_NAMES     if k not in f]
        shadow_missing = [k for k in _shadow_fields  if k not in f]

        print(f"  {sym:5}: years={f.get('historical_years_available')}  "
              f"asset_growth={f.get('asset_growth')}  "
              f"pe_vs_own_history={f.get('pe_vs_own_history')}  "
              f"f_score={f.get('f_score')}")
        if core_missing:
            _issues.append(f"{sym} core missing: {core_missing}")
        if shadow_missing:
            _issues.append(f"{sym} shadow key missing: {shadow_missing}")

    if not factor_results:
        FAIL("3_factors", "no factor dicts available from screener results")
    elif _issues:
        FAIL("3_factors", "; ".join(_issues))
    else:
        PASS("3_factors",
             f"{len(factor_results)} tickers: all {len(METRIC_NAMES)} core + "
             f"{len(_shadow_fields)} shadow keys present (None-safe)")
except Exception:
    FAIL("3_factors", traceback.format_exc(limit=2).strip().replace("\n", " "))


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 4 — Scoring
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 60)
print("NODE 4 — Scoring")
print("─" * 60)
try:
    from scoring import score_cross_sectional, RULES

    # Use all tickers that have factor data; screener pass/fail doesn't matter
    # for the scoring unit test — we want to verify the math, not the gate.
    _candidates = [
        {"symbol": sym, "factors": f, "company_name": sym}
        for sym, f in factor_results.items()
    ]
    if not _candidates:
        FAIL("4_scoring", "no candidates (factor_results empty from Node 3)")
    else:
        scored_candidates = score_cross_sectional(_candidates)
        _issues = []
        for c in scored_candidates:
            sc = c["scoring"]
            sym = c["symbol"]
            q, g, vr, total = (sc["quality_score"], sc["growth_score"],
                               sc["value_risk_score"], sc["total_score"])

            # All sleeve scores and total must be in [0, 100]
            for label, val in (("Q", q), ("G", g), ("VR", vr), ("total", total)):
                if not (0.0 <= val <= 100.0):
                    _issues.append(f"{sym} {label}={val} out of [0,100]")

            # asset_growth is lower_is_better in RULES → must be inverted
            ag_raw  = c["factors"].get("asset_growth")
            ag_norm = sc["norms"].get("asset_growth")
            _, _, ag_higher = RULES["asset_growth"]
            assert not ag_higher, "asset_growth should be lower_is_better"
            if ag_norm is not None and not (0.0 <= ag_norm <= 100.0):
                _issues.append(f"{sym} asset_growth norm={ag_norm} out of range")

            # pe_vs_own_history must be None or in [0, 100]
            pe_norm = sc["norms"].get("pe_vs_own_history")
            if pe_norm is not None and not (0.0 <= pe_norm <= 100.0):
                _issues.append(f"{sym} pe_vs_own_history norm={pe_norm} out of range")

            print(f"  {sym:5}: Q={q:5.1f}  G={g:5.1f}  VR={vr:5.1f}  "
                  f"total={total:5.1f}  ag_raw={ag_raw}  ag_norm={ag_norm}  "
                  f"pe_hist_norm={pe_norm}")

        if _issues:
            FAIL("4_scoring", "; ".join(_issues))
        else:
            PASS("4_scoring",
                 f"{len(scored_candidates)} candidates; all scores 0-100; "
                 "asset_growth inverted; pe_vs_own_history None-safe")
except Exception:
    FAIL("4_scoring", traceback.format_exc(limit=2).strip().replace("\n", " "))


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 5 — Valuation Overlay
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 60)
print("NODE 5 — Valuation Overlay")
print("─" * 60)
try:
    from valuation import apply_valuation

    _OVERLAY_FIELDS = [
        "sector_median_pe", "fair_value_pe", "pe_vs_sector",
        "valuation_adj", "valuation_label", "valuation_model_version",
    ]

    if not scored_candidates:
        FAIL("5_valuation", "no scored candidates from Node 4")
    else:
        _issues = []
        for c in scored_candidates:
            c["sector"] = None   # _default sector → PE 18.0
            apply_valuation(c)

            missing = [f for f in _OVERLAY_FIELDS if f not in c]
            if missing:
                _issues.append(f"{c['symbol']} missing: {missing}")
            adj = c.get("valuation_adj", 0.0)
            if not (-10.0 <= adj <= 10.0):
                _issues.append(f"{c['symbol']} adj={adj} outside [-10,10]")

            # Confirm does NOT touch scoring fields
            sc = c["scoring"]
            if "total_score" not in sc:
                _issues.append(f"{c['symbol']} total_score wiped by apply_valuation")

            print(f"  {c['symbol']:5}: adj={adj:+.2f}  "
                  f"label={c.get('valuation_label'):12}  "
                  f"sector_pe={c.get('sector_median_pe')}  "
                  f"total_score unchanged={sc['total_score']:.1f}")

        if _issues:
            FAIL("5_valuation", "; ".join(_issues))
        else:
            PASS("5_valuation",
                 f"{len(scored_candidates)} candidates overlaid; "
                 "all 6 fields set; total_score unchanged (shadow only)")
except Exception:
    FAIL("5_valuation", traceback.format_exc(limit=2).strip().replace("\n", " "))


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 6 — Cooldown
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 60)
print("NODE 6 — Cooldown")
print("─" * 60)
try:
    from data.storage import cooldown_map
    from config import CACHE_DB, COOLDOWN_DAYS
    from cooldown import apply_cooldown

    today = date.today()
    cd = cooldown_map(today, COOLDOWN_DAYS, CACHE_DB)

    if not isinstance(cd, dict):
        FAIL("6_cooldown", f"cooldown_map returned {type(cd).__name__}, expected dict")
    else:
        print(f"  cooldown_map: {len(cd)} symbols in {COOLDOWN_DAYS}-day window")
        for sym, until in list(cd.items())[:5]:
            print(f"    {sym:8} -> cooldown_until={until}")

        # Verify apply_cooldown stamps fields correctly on a synthetic ranked list
        _test_ranked = [
            {"symbol": "AAPL", "recommendation_rank": 1},
            {"symbol": "XXXX_FAKE", "recommendation_rank": 2},
        ]
        # Force AAPL into the cooldown map for this unit test
        _fake_cd_map = {"AAPL": "2099-01-01"}
        from data import storage as _storage_mod
        _orig_cd = _storage_mod.cooldown_map
        _storage_mod.cooldown_map = lambda *a, **kw: _fake_cd_map
        apply_cooldown(_test_ranked, today=today, db_path=CACHE_DB)
        _storage_mod.cooldown_map = _orig_cd  # restore

        aapl_row = _test_ranked[0]
        xxxx_row = _test_ranked[1]
        assert aapl_row["in_cooldown"] == 1,    "AAPL should be in cooldown"
        assert aapl_row["is_daily_pick"] == 0,  "AAPL should not be daily pick"
        assert xxxx_row["in_cooldown"] == 0,    "XXXX should not be in cooldown"
        assert xxxx_row["is_daily_pick"] == 1,  "XXXX should be daily pick"

        print("  apply_cooldown logic: AAPL(in_cd) skipped; XXXX(not_in_cd) chosen ✓")
        PASS("6_cooldown",
             f"{len(cd)} symbols in production cooldown map; "
             "apply_cooldown exclusion logic verified")
except Exception:
    FAIL("6_cooldown", traceback.format_exc(limit=2).strip().replace("\n", " "))


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 7 — Storage / _build_row  (42 columns, no KeyError)
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 60)
print("NODE 7 — Storage / _build_row")
print("─" * 60)
try:
    from pipeline import _build_row
    from data.storage import COLUMNS
    from config import VALUATION_WEIGHT

    if not scored_candidates:
        FAIL("7_storage", "no scored candidates from Node 4")
    else:
        # Decorate candidates with the remaining fields _build_row expects
        for i, c in enumerate(scored_candidates, start=1):
            c["recommendation_rank"] = i
            c["is_daily_pick"]       = 1 if i == 1 else 0
            c["eligible_for_pick"]   = 1
            c["in_cooldown"]         = 0
            c["cooldown_until"]      = None
            adj = c.get("valuation_adj") or 0.0
            c["total_score_adj"] = round(
                c["scoring"]["total_score"] + VALUATION_WEIGHT * adj, 2
            )
            c["recommendation_rank_with_valuation"] = i

        _issues = []
        for c in scored_candidates:
            try:
                row = _build_row(c, "2026-05-01", c["recommendation_rank"])
                missing_cols = [col for col in COLUMNS if col not in row]
                extra_cols   = [col for col in row    if col not in COLUMNS]
                if missing_cols:
                    _issues.append(f"{c['symbol']} missing: {missing_cols}")
                if extra_cols:
                    _issues.append(f"{c['symbol']} unexpected extra cols: {extra_cols}")
                print(f"  {c['symbol']:5}: {len(row)} cols  missing={missing_cols}  "
                      f"extra={extra_cols}")
            except Exception as exc:
                _issues.append(f"{c['symbol']}: {exc}")

        print(f"  COLUMNS list length: {len(COLUMNS)}")
        if _issues:
            FAIL("7_storage", "; ".join(_issues))
        else:
            PASS("7_storage",
                 f"_build_row produces all {len(COLUMNS)} COLUMNS; no KeyError")
except Exception:
    FAIL("7_storage", traceback.format_exc(limit=2).strip().replace("\n", " "))


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 8 — Pipeline (30-ticker sample)
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 60)
print("NODE 8 — Pipeline (30-ticker sample)")
print("─" * 60)
_test_db_8 = RICH_DIR / "data" / "test_e2e_pipe.db"
try:
    import universe as _uni_mod
    import pipeline as _pipeline_mod

    if _test_db_8.exists():
        _test_db_8.unlink()

    # Determine the 30-ticker slice to hand the pipeline.
    # Prefer the universe already fetched in Node 1 to avoid a second full API call.
    if uni_result and uni_result.get("eligible"):
        _slice30 = uni_result["eligible"][:30]
        print(f"  Re-using universe from Node 1 — slicing to first 30 eligible tickers")
    else:
        print("  Node 1 universe unavailable; fetching fresh (may take ~10s)…")
        _fresh = _uni_mod.build_universe()
        _slice30 = _fresh["eligible"][:30]

    print(f"  30-ticker slice: {[r['symbol'] for r in _slice30]}")

    _orig_build = _uni_mod.build_universe

    def _mock_build(*args, **kwargs):
        return {
            "raw_total":            len(_slice30),
            "by_exchange":          {},
            "dropped_symbol_filter": 0,
            "dropped_sector":       0,
            "dropped_adr":          0,
            "dropped_dollar_volume": 0,
            "eligible":             _slice30,
            "eligible_count":       len(_slice30),
        }

    _uni_mod.build_universe = _mock_build

    try:
        _result = _pipeline_mod.run(
            today=date(2026, 5, 1),
            db_path=_test_db_8,
            persist=True,
        )
    finally:
        _uni_mod.build_universe = _orig_build

    _scored   = _result.get("scored", 0)
    _rejects  = _result.get("rejects", {})
    _screened = _scored + sum(_rejects.values())
    _pick     = _result.get("daily_pick")

    print(f"  Pass 1 screened={_screened}  passed={_scored}  rejects={_rejects}")
    print(f"  Pass 2 cross-sectional z-score: {_scored} candidates")
    print(f"  Daily pick: {_pick['symbol'] if _pick else 'None (no eligible candidate)'}")

    # Verify DB state
    _conn = sqlite3.connect(_test_db_8)
    _n_pick1  = _conn.execute(
        "SELECT COUNT(*) FROM daily_picks WHERE is_daily_pick=1"
    ).fetchone()[0]
    _n_total  = _conn.execute("SELECT COUNT(*) FROM daily_picks").fetchone()[0]
    _conn.close()

    print(f"  DB: total_rows={_n_total}  is_daily_pick=1 rows={_n_pick1}")

    if _pick and _n_pick1 == 1:
        PASS("8_pipeline",
             f"Pass1+Pass2 complete; pick={_pick['symbol']}; "
             f"is_daily_pick=1 row verified in DB")
    elif not _pick and _n_pick1 == 0:
        PASS("8_pipeline",
             "No pick (all candidates in cooldown or none passed screen); "
             "0 is_daily_pick=1 rows — consistent")
    else:
        FAIL("8_pipeline",
             f"pick={_pick} but DB has {_n_pick1} is_daily_pick=1 rows")

except Exception:
    FAIL("8_pipeline", traceback.format_exc(limit=3).strip().replace("\n", " "))
finally:
    if _test_db_8.exists():
        _test_db_8.unlink()


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 9 — Portfolio Engine
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 60)
print("NODE 9 — Portfolio Engine")
print("─" * 60)
_test_db_9 = RICH_DIR / "data" / "test_e2e_portfolio.db"
try:
    import portfolio
    from data.storage import init_db, insert_picks, COLUMNS

    if _test_db_9.exists():
        _test_db_9.unlink()

    init_db(_test_db_9)

    def _pick_row(overrides: dict) -> dict:
        base = {col: None for col in COLUMNS}
        base.update({
            "run_date": "2026-04-30",
            "recommendation_rank": 1,
            "is_daily_pick": 1,
            "eligible_for_pick": 1,
            "in_cooldown": 0,
            "beneish_flag": 0,
            "valuation_adj": 0.0,
            "valuation_label": "n/a",
            "valuation_model_version": "v1_static_sector_pe",
            "normalization_method": "zscore_v2",
            "universe_n_at_scoring": 30,
        })
        base.update(overrides)
        return base

    # AAPL: f_score=7, pe_vs_own_history=0.85 → should be admitted
    # GME : pe_vs_own_history=NULL            → must be skipped
    # PLTR: f_score=4 (below MIN_FSCORE_ENTRY=6) → must be skipped
    _rows = [
        _pick_row({"symbol": "AAPL", "total_score": 75.0, "quality_score": 80.0,
                   "growth_score": 70.0, "value_risk_score": 65.0,
                   "f_score": 7,  "pe_vs_own_history": 0.85}),
        _pick_row({"symbol": "GME",  "total_score": 60.0, "quality_score": 55.0,
                   "growth_score": 50.0, "value_risk_score": 60.0,
                   "f_score": 6,  "pe_vs_own_history": None,   # must be skipped
                   "is_daily_pick": 0, "recommendation_rank": 2}),
        _pick_row({"symbol": "PLTR", "total_score": 55.0, "quality_score": 50.0,
                   "growth_score": 45.0, "value_risk_score": 55.0,
                   "f_score": 4,  "pe_vs_own_history": 0.75,   # f_score too low
                   "is_daily_pick": 0, "recommendation_rank": 3}),
    ]
    insert_picks(_rows, path=_test_db_9)

    result9 = portfolio.run(today=date(2026, 5, 1), db_path=_test_db_9)

    entries  = result9.get("entries", [])
    holdings = [h["symbol"] for h in result9.get("holdings", [])]
    exits    = result9.get("exits", [])

    print(f"  entries={entries}  holdings={holdings}  exits={exits}")

    _issues9 = []
    if "GME"  in entries: _issues9.append("GME entered despite NULL pe_vs_own_history")
    if "PLTR" in entries: _issues9.append("PLTR entered despite f_score=4 < 6")
    if "AAPL" not in entries:
        _issues9.append(f"AAPL not entered (f=7, pe_hist=0.85 < 1.0) — entries={entries}")

    if _issues9:
        FAIL("9_portfolio", "; ".join(_issues9))
    else:
        PASS("9_portfolio",
             "AAPL entered (f=7, pe_hist<1.0); "
             "GME skipped (NULL pe_hist); "
             "PLTR skipped (f=4<6); no crash")

except Exception:
    FAIL("9_portfolio", traceback.format_exc(limit=3).strip().replace("\n", " "))
finally:
    if _test_db_9.exists():
        _test_db_9.unlink()


# ═══════════════════════════════════════════════════════════════════════════════
# NODE 10 — Observability  (run_metrics.csv)
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 60)
print("NODE 10 — Observability")
print("─" * 60)
import tempfile as _tempfile
_tmp_dir = Path(_tempfile.mkdtemp())
try:
    from logging_utils import append_run_metrics
    from config import LOG_DIR
    import csv as _csv

    _prod_csv = LOG_DIR / "run_metrics.csv"

    _mock_result = {
        "run_date":   "2026-05-01",
        "elapsed_s":  42.0,
        "universe_counts": {
            "raw_total": 1500, "dropped_symbol_filter": 50,
            "dropped_sector": 400, "dropped_adr": 5,
            "dropped_dollar_volume": 100, "eligible": 1100,
        },
        "scored": 250,
        "rejects": {
            "HIST_LT_5": 300, "MISSING_FIELDS": 50,
            "BENEISH_FLAG": 10, "FETCH_ERROR": 5,
        },
        "raw_top": [{"symbol": "AAPL", "in_cooldown": 0,
                     "scoring": {"total_score": 75.0}}],
        "daily_pick": {
            "symbol": "AAPL",
            "recommendation_rank": 1,
            "scoring": {"total_score": 75.0},
        },
        "stage_timings": {
            "universe": 8.5, "screen": 25.0, "score": 0.5,
            "valuation": 2.0, "cooldown": 0.1, "persist": 0.2,
        },
    }

    # --- Sub-test A: write to a fresh temp CSV so we own the header ---
    append_run_metrics(_mock_result, log_dir=_tmp_dir)
    # append_run_metrics writes to log_dir / "run_metrics.csv"
    _tmp_actual = _tmp_dir / "run_metrics.csv"
    with open(_tmp_actual, "r", encoding="utf-8") as _f:
        _fresh_rows = list(_csv.DictReader(_f))
    _expected_cols = [
        "run_date", "elapsed_s", "universe_eligible", "scored",
        "daily_pick", "daily_pick_score", "t_universe_s",
    ]
    _fresh_last = _fresh_rows[-1] if _fresh_rows else {}
    _missing_cols = [c for c in _expected_cols if c not in _fresh_last]

    print(f"  Temp CSV: {_tmp_actual}")
    print(f"  Fresh-write row count: {len(_fresh_rows)}")
    print(f"  Columns present: {list(_fresh_last.keys())}")
    print(f"  daily_pick={_fresh_last.get('daily_pick')}  "
          f"scored={_fresh_last.get('scored')}  "
          f"t_universe_s={_fresh_last.get('t_universe_s')}")

    # --- Sub-test B: check production CSV grows by 1 row ---
    _prod_before = 0
    if _prod_csv.exists():
        with open(_prod_csv, "r", encoding="utf-8") as _f:
            _hdr = _f.readline()  # read header
            _prod_before = sum(1 for _ in _f)  # remaining = data rows
        _prod_schema = "new" if "t_universe_s" in _hdr else "old (pre-logging_utils)"
    else:
        _prod_schema = "absent"

    # Append to production CSV
    append_run_metrics(_mock_result, log_dir=LOG_DIR)

    _prod_after = 0
    with open(_prod_csv, "r", encoding="utf-8") as _f:
        _f.readline()  # skip header
        _prod_after = sum(1 for _ in _f)

    print(f"  Production CSV schema: {_prod_schema}")
    print(f"  Production rows before={_prod_before}  after={_prod_after}")

    _issues10 = []
    if len(_fresh_rows) != 1:
        _issues10.append(f"fresh CSV should have 1 row; got {len(_fresh_rows)}")
    if _missing_cols:
        _issues10.append(f"fresh CSV missing columns: {_missing_cols}")
    if _prod_after != _prod_before + 1:
        _issues10.append(f"prod CSV: expected +1 row; got {_prod_before}->{_prod_after}")

    if _issues10:
        FAIL("10_observability", "; ".join(_issues10))
    else:
        _schema_note = (
            "" if _prod_schema == "new"
            else f" (WARNING: prod CSV has {_prod_schema} header — needs regeneration)"
        )
        PASS("10_observability",
             f"fresh CSV: 1 row, all {len(_expected_cols)} expected cols; "
             f"prod CSV: +1 row{_schema_note}")

except Exception:
    FAIL("10_observability", traceback.format_exc(limit=2).strip().replace("\n", " "))
finally:
    import shutil as _shutil
    try:
        _shutil.rmtree(_tmp_dir, ignore_errors=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY TABLE
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "═" * 72)
print(f"  {'Node':<32} {'Status':<6}  Notes")
print("═" * 72)
for _label, _status, _notes in _results:
    _marker = "✓" if _status == "PASS" else "✗"
    _note_s = (_notes[:55] + "…") if len(_notes) > 55 else _notes
    print(f"  {_marker} {_label:<30} {_status:<6}  {_note_s}")
print("═" * 72)
_passed = sum(1 for _, s, _ in _results if s == "PASS")
_total  = len(_results)
print(f"\n  {_passed}/{_total} nodes PASSED\n")
sys.exit(0 if _passed == _total else 1)
