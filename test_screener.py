"""Sample-ticker test for factor extraction + per-ticker screening."""
from __future__ import annotations

import json

from data.fetcher import FMPClient
from screener import screen_ticker

# Mix: mega-cap, small profitable, possible-rejects
SAMPLES = ["AAPL", "MSFT", "PLTR", "T", "GME"]


def main() -> None:
    client = FMPClient()
    print(f"Screening {len(SAMPLES)} sample tickers (rules 4-7)\n")
    for sym in SAMPLES:
        r = screen_ticker(sym, client)
        f = r["factors"] or {}
        verdict = "PASS" if r["pass"] else f"REJECT [{r['reason']}]"
        print(f"=== {sym} :: {verdict} ===")
        if r["detail"]:
            print(f"  detail: {r['detail']}")
        if f:
            print(f"  fiscalYear={f.get('fiscalYear')} "
                  f"hist={f.get('historical_years_available')} "
                  f"({f.get('history_class')})")
            print(f"  revenue={f.get('revenue'):,}" if f.get("revenue") else "  revenue=None")
            print(f"  netIncome={f.get('netIncome'):,}" if f.get("netIncome") else "  netIncome=None")
            print(f"  OCF={f.get('operatingCashFlow'):,}" if f.get("operatingCashFlow") else "  OCF=None")
            print("  factors:")
            for m in ["returnOnEquity", "returnOnAssets", "grossProfitMargin",
                      "operatingProfitMargin", "operatingCashFlowToNetIncome",
                      "revenueGrowth", "debtToEquityRatio", "priceEarningsRatio"]:
                v = f.get(m)
                vs = f"{v:.4f}" if isinstance(v, (int, float)) else str(v)
                print(f"    {m:32} = {vs}")
        print()


if __name__ == "__main__":
    main()
