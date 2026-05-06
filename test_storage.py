"""Minimal storage test: schema init, insert, cooldown query, fetch."""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

# Use temp DB so we don't touch real cache.db
TEST_DB = Path(__file__).parent / "data" / "test_cache.db"
if TEST_DB.exists():
    TEST_DB.unlink()

from data import storage

today = date(2026, 4, 25)
yesterday = today - timedelta(days=1)
old = today - timedelta(days=70)

storage.init_db(TEST_DB)
print("[1] schema initialized")

# Two prior daily picks: AAPL yesterday (in cooldown), MSFT 70d ago (expired)
storage.insert_picks([
    {"run_date": yesterday.isoformat(), "symbol": "AAPL",
     "company_name": "Apple Inc.", "total_score": 75.0,
     "quality_score": 90, "growth_score": 60, "value_risk_score": 50,
     "recommendation_rank": 1, "is_daily_pick": 1, "eligible_for_pick": 1,
     "in_cooldown": 0, "cooldown_until": None,
     "historical_years_available": 10,
     "top_drivers": "returnOnEquity,grossProfitMargin",
     "bottom_drivers": "priceEarningsRatio,debtToEquityRatio",
     "short_reason": "high quality, fair price"},
    {"run_date": old.isoformat(), "symbol": "MSFT",
     "company_name": "Microsoft Corp.", "total_score": 72.0,
     "quality_score": 85, "growth_score": 65, "value_risk_score": 55,
     "recommendation_rank": 1, "is_daily_pick": 1, "eligible_for_pick": 1,
     "in_cooldown": 0, "cooldown_until": None,
     "historical_years_available": 10,
     "top_drivers": "returnOnEquity,operatingProfitMargin",
     "bottom_drivers": "priceEarningsRatio,revenueGrowth",
     "short_reason": "stable mega-cap"},
], path=TEST_DB)
print("[2] inserted 2 historical picks")

cd = storage.cooldown_map(today, cooldown_days=60, path=TEST_DB)
print(f"[3] cooldown_map(today=2026-04-25, days=60) = {cd}")
assert "AAPL" in cd, "AAPL should be in cooldown"
assert "MSFT" not in cd, "MSFT should be expired"
print("[4] AAPL in cooldown, MSFT expired — OK")

rows = storage.fetch_run(yesterday.isoformat(), path=TEST_DB)
print(f"[5] fetch_run yesterday: {len(rows)} row(s), top={rows[0]['symbol']} score={rows[0]['total_score']}")

TEST_DB.unlink()
print("[OK] storage layer verified")
