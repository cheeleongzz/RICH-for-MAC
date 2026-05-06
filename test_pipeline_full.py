"""Full end-to-end dry run on the 1558 universe. Reports counts + top 20 + stored rows."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Use a separate DB so we don't touch any real cooldown state
TEST_DB = Path(__file__).parent / "data" / "test_pipeline.db"
if TEST_DB.exists():
    TEST_DB.unlink()

from pipeline import run

result = run(today=date(2026, 4, 25), db_path=TEST_DB)

print("\n========== DRY RUN SUMMARY ==========")
print(f"run_date       : {result['run_date']}")
print(f"elapsed        : {result['elapsed_s']} s")
print(f"universe       : {result['universe_counts']}")
print(f"scored         : {result['scored']}")
print(f"rejects by code:")
for code, n in sorted(result["rejects"].items(), key=lambda x: -x[1]):
    print(f"   {code:24} {n}")

print("\n----- Top 20 ranked -----")
print(f"{'rank':>4} {'sym':6} {'tot':>5} {'Q':>4} {'G':>4} {'VR':>4} {'cd':>3} {'pick':>4} company")
for c in result["raw_top"]:
    sc = c["scoring"]
    print(f"{c['recommendation_rank']:>4} {c['symbol']:6} "
          f"{sc['total_score']:>5.1f} {sc['quality_score']:>4.0f} "
          f"{sc['growth_score']:>4.0f} {sc['value_risk_score']:>4.0f} "
          f"{c['in_cooldown']:>3} {c['is_daily_pick']:>4} "
          f"{(c.get('company_name') or '')[:40]}")

print("\n----- Rows written to daily_picks -----")
for r in result["daily_picks_rows"]:
    print(f"  rank={r['recommendation_rank']} {r['symbol']:6} "
          f"total={r['total_score']} pick={r['is_daily_pick']} "
          f"elig={r['eligible_for_pick']} hist={r['historical_years_available']} "
          f"reason='{r['short_reason']}'")

pick = result.get("daily_pick")
print(f"\nDAILY PICK: {pick['symbol'] if pick else '<none>'}")
