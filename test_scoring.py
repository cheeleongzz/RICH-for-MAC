"""Validate Phase 3.2 + 3.3 activation: screen samples, run cross-sectional scorer, show breakdown."""
from __future__ import annotations

from data.fetcher import FMPClient
from screener import screen_ticker
from scoring import score_cross_sectional, GROWTH_METRICS, VALUE_RISK_METRICS

SAMPLES = ["AAPL", "MSFT", "PLTR", "T", "GME"]


def _fmt(v: float | None) -> str:
    return f"{v:6.1f}" if v is not None else "  None"


def main() -> None:
    client = FMPClient()
    candidates = []
    for sym in SAMPLES:
        s = screen_ticker(sym, client)
        if not s["pass"]:
            print(f"{sym}  REJECT [{s['reason']}]")
            continue
        candidates.append({"symbol": sym, "company_name": sym, "factors": s["factors"]})

    if not candidates:
        print("No candidates passed screening.")
        return

    scored = score_cross_sectional(candidates)

    for c in scored:
        sc = c["scoring"]
        f  = c["factors"]
        print(f"=== {c['symbol']}  total={sc['total_score']}  "
              f"Q={sc['quality_score']:.0f} G={sc['growth_score']:.0f} VR={sc['value_risk_score']:.0f} ===")
        print("  -- Growth sleeve --")
        for m in GROWTH_METRICS:
            print(f"    {m:32}  raw={str(f.get(m))[:14]:14}  z={_fmt(sc['norms'].get(m))}")
        print("  -- Value/Risk sleeve --")
        for m in VALUE_RISK_METRICS:
            print(f"    {m:32}  raw={str(f.get(m))[:14]:14}  z={_fmt(sc['norms'].get(m))}")
        print(f"  top_2:    {sc['top_2_drivers']}")
        print(f"  bottom_2: {sc['bottom_2_drivers']}")
        print()

    print("=== Cross-sectional ranking ===")
    for i, c in enumerate(
        sorted(scored, key=lambda x: x["scoring"]["total_score"], reverse=True), 1
    ):
        sc = c["scoring"]
        print(f"  {i}. {c['symbol']:6}  total={sc['total_score']:5.1f}  "
              f"Q={sc['quality_score']:.0f} G={sc['growth_score']:.0f} VR={sc['value_risk_score']:.0f}")


if __name__ == "__main__":
    main()
