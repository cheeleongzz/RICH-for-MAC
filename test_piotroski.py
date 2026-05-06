"""Smoke test: Piotroski F-Score on synthetic firms. No network required."""
from __future__ import annotations

import piotroski

# ── "Good" firm: all 9 signals should fire ──────────────────────────────────
# Verified manually (see comments at end of file):
GOOD_INC0 = {"netIncome": 100, "revenue": 1000, "grossProfit": 400,
              "weightedAverageShsOut": 100}
GOOD_INC1 = {"netIncome": 80,  "revenue": 800,  "grossProfit": 300,
              "weightedAverageShsOut": 110}
GOOD_BS0  = {"totalAssets": 800, "longTermDebt": 100,
             "totalCurrentAssets": 300, "totalCurrentLiabilities": 100}
GOOD_BS1  = {"totalAssets": 750, "longTermDebt": 120,
             "totalCurrentAssets": 200, "totalCurrentLiabilities": 100}
GOOD_CF0  = {"operatingCashFlow": 120}

# ── "Bad" firm: no signal should fire ───────────────────────────────────────
BAD_INC0 = {"netIncome": -50, "revenue": 1000, "grossProfit": 200,
             "weightedAverageShsOut": 200}
BAD_INC1 = {"netIncome": -30, "revenue": 1100, "grossProfit": 250,
             "weightedAverageShsOut": 180}
BAD_BS0  = {"totalAssets": 800, "longTermDebt": 400,
            "totalCurrentAssets": 100, "totalCurrentLiabilities": 200}
BAD_BS1  = {"totalAssets": 700, "longTermDebt": 200,
            "totalCurrentAssets": 150, "totalCurrentLiabilities": 150}
BAD_CF0  = {"operatingCashFlow": -70}


def _run(label: str, inc0, inc1, bs0, bs1, cf0, expected: int) -> None:
    signals = piotroski.compute_f_signals(inc0, inc1, bs0, bs1, cf0)
    score   = piotroski.f_score(signals)
    status  = "OK" if score == expected else f"FAIL (got {score}, want {expected})"
    print(f"[{label}] signals={signals}")
    print(f"         f_score={score}  [{status}]")
    assert score == expected, f"{label}: expected {expected}, got {score}"


def main() -> None:
    _run("GOOD_FIRM", GOOD_INC0, GOOD_INC1, GOOD_BS0, GOOD_BS1, GOOD_CF0, expected=9)
    _run("BAD_FIRM",  BAD_INC0,  BAD_INC1,  BAD_BS0,  BAD_BS1,  BAD_CF0,  expected=0)
    print("\n[OK] piotroski smoke test passed")


if __name__ == "__main__":
    main()

# ── Manual verification for GOOD_FIRM ───────────────────────────────────────
# F1  ROA0 = 100/800 = 0.125  > 0                              → 1
# F2  OCF  = 120 > 0                                           → 1
# F3  ROA1 = 80/750 ≈ 0.107, ROA0 > ROA1                      → 1
# F4  CFO/TA = 120/800 = 0.15 > ROA0 = 0.125                  → 1
# F5  lev0 = 100/800=0.125, lev1=120/750=0.16, lev0 < lev1    → 1
# F6  cr0 = 300/100=3.0, cr1=200/100=2.0, cr0 > cr1           → 1
# F7  shs0=100 ≤ shs1=110                                      → 1
# F8  gm0 = 400/1000=0.40, gm1=300/800=0.375, gm0 > gm1       → 1
# F9  at0 = 1000/800=1.25, at1=800/750≈1.067, at0 > at1       → 1
#
# ── Manual verification for BAD_FIRM ────────────────────────────────────────
# F1  ROA0 = -50/800 = -0.0625 ≤ 0                             → 0
# F2  OCF  = -70 ≤ 0                                            → 0
# F3  ROA1 = -30/700≈-0.043, ROA0 < ROA1 (worse)               → 0
# F4  CFO/TA=-70/800=-0.0875, roa0=-0.0625, cfo_over_a < roa0  → 0
# F5  lev0=400/800=0.5, lev1=200/700≈0.286, lev0 > lev1        → 0
# F6  cr0=100/200=0.5, cr1=150/150=1.0, cr0 < cr1              → 0
# F7  shs0=200 > shs1=180 (dilution occurred)                   → 0
# F8  gm0=200/1000=0.20, gm1=250/1100≈0.227, gm0 < gm1         → 0
# F9  at0=1000/800=1.25, at1=1100/700≈1.571, at0 < at1         → 0
