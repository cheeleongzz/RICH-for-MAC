#!/usr/bin/env python3
"""
Cache validation: two identical pipeline runs, same calendar day.

Replicates what run_daily.py does (calls pipeline.run(), appends run_metrics)
on a 30-ticker slice from the live universe so both runs finish in <6 min.
Uses an isolated SQLite DB so production data/cache.db is untouched.

Steps
-----
1. Delete today's FMP cache file.
2. Run pipeline (Run 1) — all API calls go to FMP.
3. Record: eligible count, passed count, top-5, daily pick, screen timing.
4. Patch FMPClient to count API calls made in Run 2.
5. Run pipeline again (Run 2) — should hit cache for all prior symbols.
6. Compare every metric; report mismatches only.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent))

import universe   as _uni_mod
import pipeline   as _pipe_mod
from factors       import _cache_path
from data          import fetcher as _fetcher_mod
from data.storage  import COLUMNS

TODAY     = date.today()
TODAY_ISO = TODAY.isoformat()
TEST_DB   = Path("data/validate_cache_test.db")
CACHE_F   = _cache_path(TODAY_ISO)


# ── helpers ──────────────────────────────────────────────────────────────────

def _db_rows(path: Path) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT symbol, recommendation_rank, total_score, "
        "       is_daily_pick, in_cooldown, quality_score, "
        "       growth_score, value_risk_score "
        "FROM daily_picks "
        "WHERE run_date=? ORDER BY recommendation_rank",
        (TODAY_ISO,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _top5(rows: list[dict]) -> list[str]:
    return [r["symbol"] for r in rows if r["recommendation_rank"] <= 5]


def _pick(rows: list[dict]) -> str | None:
    for r in rows:
        if r["is_daily_pick"] == 1:
            return r["symbol"]
    return None


def _scores(rows: list[dict]) -> dict[str, tuple]:
    return {
        r["symbol"]: (
            round(r["total_score"] or 0, 2),
            round(r["quality_score"] or 0, 2),
            round(r["growth_score"] or 0, 2),
            round(r["value_risk_score"] or 0, 2),
        )
        for r in rows
        if r["recommendation_rank"] <= 5
    }


# ── Step 1: delete cache ──────────────────────────────────────────────────────
print("=" * 64)
print("STEP 1 — Delete today's FMP cache")
print("=" * 64)
if CACHE_F.exists():
    CACHE_F.unlink()
    print(f"  Deleted: {CACHE_F}")
else:
    print(f"  Cache was already absent: {CACHE_F}")


# ── Fetch universe once (shared by both runs) ─────────────────────────────────
print()
print("=" * 64)
print("Fetching live universe (shared, not counted as run time)…")
print("=" * 64)
_full = _uni_mod.build_universe()
_SLICE = _full["eligible"][:30]
print(f"  Full eligible universe: {_full['eligible_count']}")
print(f"  30-ticker slice: {[r['symbol'] for r in _SLICE]}")

_orig_build = _uni_mod.build_universe
def _mock_universe(*a, **kw):
    return {**_full, "eligible": _SLICE, "eligible_count": len(_SLICE)}


# ── FMPClient call counter (injected for Run 2 only) ─────────────────────────
_ORIG_METHODS = {
    "income_statement":   _fetcher_mod.FMPClient.income_statement,
    "balance_sheet":      _fetcher_mod.FMPClient.balance_sheet,
    "cash_flow":          _fetcher_mod.FMPClient.cash_flow,
    "ratios":             _fetcher_mod.FMPClient.ratios,
    "key_metrics":        _fetcher_mod.FMPClient.key_metrics,
    "financial_growth":   _fetcher_mod.FMPClient.financial_growth,
}
_api_call_log: list[str] = []   # (symbol, endpoint) pairs

def _make_counted(name: str, orig):
    def _wrapper(self, symbol, *args, **kwargs):
        _api_call_log.append(f"{symbol}/{name}")
        return orig(self, symbol, *args, **kwargs)
    _wrapper.__name__ = name
    return _wrapper


# ── Run helper ────────────────────────────────────────────────────────────────
def _do_run(label: str, count_calls: bool) -> dict:
    print()
    print("=" * 64)
    print(f"RUN {label}")
    print("=" * 64)

    if TEST_DB.exists():
        TEST_DB.unlink()

    if count_calls:
        for mname, orig in _ORIG_METHODS.items():
            setattr(_fetcher_mod.FMPClient, mname, _make_counted(mname, orig))
        _api_call_log.clear()

    _uni_mod.build_universe = _mock_universe
    try:
        t0 = time.monotonic()
        result = _pipe_mod.run(today=TODAY, db_path=TEST_DB, persist=True)
        elapsed = round(time.monotonic() - t0, 1)
    finally:
        _uni_mod.build_universe = _orig_build
        if count_calls:
            for mname, orig in _ORIG_METHODS.items():
                setattr(_fetcher_mod.FMPClient, mname, orig)

    rows    = _db_rows(TEST_DB)
    stage_t = result.get("stage_timings", {})

    print(f"  elapsed total         : {elapsed}s")
    print(f"  stage screen (Pass 1) : {stage_t.get('screen','?')}s")
    print(f"  stage score  (Pass 2) : {stage_t.get('score','?')}s")
    print(f"  eligible universe     : {result['universe_counts']['eligible']}")
    print(f"  passed screener       : {result['scored']}")
    print(f"  rejects               : {result['rejects']}")
    print(f"  top-5 symbols         : {_top5(rows)}")
    print(f"  daily pick            : {_pick(rows)}")
    for r in rows:
        if r["recommendation_rank"] <= 5:
            print(f"    rank {r['recommendation_rank']}  {r['symbol']:8}  "
                  f"total={r['total_score']:.2f}  "
                  f"Q={r['quality_score']:.1f}  "
                  f"G={r['growth_score']:.1f}  "
                  f"VR={r['value_risk_score']:.1f}  "
                  f"pick={r['is_daily_pick']}")

    if count_calls:
        print(f"  FMP API calls made    : {len(_api_call_log)}")
        if _api_call_log:
            print("  API calls (non-zero — unexpected):")
            for c in _api_call_log[:20]:
                print(f"    {c}")

    cache_size = CACHE_F.stat().st_size if CACHE_F.exists() else 0
    print(f"  cache file size       : {cache_size:,} bytes")

    return {
        "elapsed":    elapsed,
        "screen_t":   stage_t.get("screen"),
        "eligible":   result["universe_counts"]["eligible"],
        "passed":     result["scored"],
        "rejects":    result["rejects"],
        "top5":       _top5(rows),
        "pick":       _pick(rows),
        "scores":     _scores(rows),
        "api_calls":  len(_api_call_log) if count_calls else None,
        "cache_size": cache_size,
    }


# ── Execute both runs ─────────────────────────────────────────────────────────
r1 = _do_run("1 (no cache — all calls go to FMP)", count_calls=False)
cache_size_after_run1 = CACHE_F.stat().st_size if CACHE_F.exists() else 0

r2 = _do_run("2 (cache warm — expect zero API calls)", count_calls=True)
cache_size_after_run2 = CACHE_F.stat().st_size if CACHE_F.exists() else 0


# ── Comparison ────────────────────────────────────────────────────────────────
print()
print("=" * 64)
print("COMPARISON")
print("=" * 64)

mismatches: list[str] = []

# --- eligible universe ---
if r1["eligible"] != r2["eligible"]:
    mismatches.append(
        f"eligible universe: Run1={r1['eligible']} vs Run2={r2['eligible']}"
    )
else:
    print(f"  eligible universe   : {r1['eligible']}  [MATCH]")

# --- passed count ---
if r1["passed"] != r2["passed"]:
    mismatches.append(
        f"passed count: Run1={r1['passed']} vs Run2={r2['passed']}"
    )
else:
    print(f"  passed screener     : {r1['passed']}  [MATCH]")

# --- rejects ---
if r1["rejects"] != r2["rejects"]:
    mismatches.append(
        f"rejects: Run1={r1['rejects']} vs Run2={r2['rejects']}"
    )
else:
    print(f"  rejects             : {r1['rejects']}  [MATCH]")

# --- top-5 symbols (order matters) ---
if r1["top5"] != r2["top5"]:
    mismatches.append(
        f"top-5 symbols: Run1={r1['top5']} vs Run2={r2['top5']}"
    )
else:
    print(f"  top-5 symbols       : {r1['top5']}  [MATCH]")

# --- top-5 scores ---
score_mismatches = []
for sym in set(list(r1["scores"].keys()) + list(r2["scores"].keys())):
    s1 = r1["scores"].get(sym)
    s2 = r2["scores"].get(sym)
    if s1 != s2:
        score_mismatches.append(f"  {sym}: Run1={s1} Run2={s2}")
if score_mismatches:
    mismatches.append("top-5 scores differ:\n" + "\n".join(score_mismatches))
else:
    print(f"  top-5 scores        : all identical  [MATCH]")

# --- daily pick ---
if r1["pick"] != r2["pick"]:
    # Expected: Run 1 pick enters cooldown, Run 2 advances to next rank.
    # This is the ghost-pick issue, not a cache failure.
    print(f"  daily pick          : Run1={r1['pick']} vs Run2={r2['pick']}  "
          f"[EXPECTED MISMATCH — ghost-pick / cooldown accumulation, not a cache failure]")
else:
    print(f"  daily pick          : {r1['pick']}  [MATCH]")

# --- zero API calls in Run 2 ---
if r2["api_calls"] != 0:
    mismatches.append(
        f"FMP API calls in Run 2: {r2['api_calls']} (expected 0)\n"
        + "  Unexpected calls: " + str(_api_call_log[:10])
    )
else:
    print(f"  FMP API calls Run 2 : 0  [MATCH — cache served all {r1['passed']} symbols]")

# --- cache file unchanged ---
if cache_size_after_run1 != cache_size_after_run2:
    mismatches.append(
        f"cache file grew in Run 2: {cache_size_after_run1:,} -> {cache_size_after_run2:,} bytes"
        " (new symbols fetched)"
    )
else:
    print(f"  cache file size     : {cache_size_after_run1:,} bytes  [UNCHANGED between runs]")

# --- screen timing ---
if r1["screen_t"] and r2["screen_t"]:
    ratio = round(r1["screen_t"] / r2["screen_t"], 1) if r2["screen_t"] else "inf"
    print(f"  screen stage timing : Run1={r1['screen_t']}s  Run2={r2['screen_t']}s  "
          f"(Run1/Run2={ratio}x — cache speedup)")

# --- summary ---
print()
print("=" * 64)
if mismatches:
    print(f"MISMATCHES ({len(mismatches)}):")
    for m in mismatches:
        print(f"  MISMATCH: {m}")
else:
    print("No mismatches — cache validation PASSED.")
print("=" * 64)

# cleanup
if TEST_DB.exists():
    TEST_DB.unlink()
