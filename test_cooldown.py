"""Synthetic test: rank 1 in cooldown -> daily pick falls through to rank 2."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

TEST_DB = Path(__file__).parent / "data" / "test_cooldown.db"
if TEST_DB.exists():
    TEST_DB.unlink()

from data import storage
from cooldown import apply_cooldown

today = date(2026, 4, 25)

# Seed: PLTR was the daily pick 10 days ago -> still in cooldown (60d window)
storage.init_db(TEST_DB)
storage.insert_picks([{
    "run_date": (today - timedelta(days=10)).isoformat(),
    "symbol": "PLTR", "company_name": "Palantir Technologies Inc.",
    "total_score": 81.0, "quality_score": 91, "growth_score": 100, "value_risk_score": 49,
    "recommendation_rank": 1, "is_daily_pick": 1, "eligible_for_pick": 1,
    "in_cooldown": 0, "cooldown_until": None,
    "historical_years_available": 8,
    "top_drivers": "returnOnAssets,grossProfitMargin",
    "bottom_drivers": "priceEarningsRatio,returnOnEquity",
    "short_reason": "growth maxed",
}], path=TEST_DB)

# Today's ranked candidates (PLTR rank 1 again, but in cooldown)
ranked = [
    {"symbol": "PLTR", "recommendation_rank": 1, "total_score": 80.7},
    {"symbol": "MSFT", "recommendation_rank": 2, "total_score": 74.7},
    {"symbol": "T",    "recommendation_rank": 3, "total_score": 58.5},
    {"symbol": "AAPL", "recommendation_rank": 4, "total_score": 56.0},
    {"symbol": "GME",  "recommendation_rank": 5, "total_score": 36.2},
]

apply_cooldown(ranked, today=today, db_path=TEST_DB)

print(f"{'sym':6} {'rank':>4} {'in_cd':>5} {'elig':>4} {'pick':>4} cooldown_until")
for r in ranked:
    print(f"{r['symbol']:6} {r['recommendation_rank']:>4} "
          f"{r['in_cooldown']:>5} {r['eligible_for_pick']:>4} "
          f"{r['is_daily_pick']:>4} {r['cooldown_until']}")

# Assertions
picks = [r for r in ranked if r["is_daily_pick"] == 1]
assert len(picks) == 1, f"expected exactly 1 pick, got {len(picks)}"
assert picks[0]["symbol"] == "MSFT", f"expected MSFT pick, got {picks[0]['symbol']}"

assert ranked[0]["symbol"] == "PLTR"
assert ranked[0]["in_cooldown"] == 1
assert ranked[0]["eligible_for_pick"] == 0
assert ranked[0]["cooldown_until"] == (today - timedelta(days=10) + timedelta(days=60)).isoformat()
assert ranked[0]["is_daily_pick"] == 0

for r in ranked:
    assert r["eligible_for_pick"] == (1 - r["in_cooldown"]), \
        f"{r['symbol']}: eligible_for_pick must invert in_cooldown"

print("\n[OK] PLTR in cooldown (until "
      f"{ranked[0]['cooldown_until']}), daily pick fell through to MSFT.")
print("[OK] Exactly one is_daily_pick=1; eligible_for_pick == NOT in_cooldown for all.")

TEST_DB.unlink()
