"""Thin runner for the read-only portfolio engine.

Usage:
    python run_portfolio.py              # run today's cycle
    python run_portfolio.py --show       # print holdings only, no cycle
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

import portfolio


def _print_holdings(holdings: list[dict]) -> None:
    if not holdings:
        print("  (none)")
        return
    print(f"  {'symbol':<8} {'entry_date':<12} {'score':>6} {'f':>3} {'pe_hist':>8}")
    print(f"  {'-'*44}")
    for h in holdings:
        score   = f"{h['entry_score']:.1f}" if h.get("entry_score") is not None else "—"
        f_val   = str(h["f_score"]) if h.get("f_score") is not None else "—"
        pe_hist = f"{h['pe_vs_own_hist']:.3f}" if h.get("pe_vs_own_hist") is not None else "—"
        print(f"  {h['symbol']:<8} {h['entry_date']:<12} {score:>6} {f_val:>3} {pe_hist:>8}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RICH portfolio engine runner")
    parser.add_argument("--show", action="store_true",
                        help="Print current holdings without running a new cycle")
    args = parser.parse_args()

    if args.show:
        holdings = portfolio.active_holdings()
        print(f"\nActive holdings ({len(holdings)}):")
        _print_holdings(holdings)
        print()
        return

    result = portfolio.run(today=date.today())

    exits   = result["exits"]
    entries = result["entries"]
    holdings = result["holdings"]

    print(f"\n{'='*60}")
    print(f"Portfolio run : {result['run_date']}   "
          f"holdings = {result['holdings_count']}/{portfolio.MAX_HOLDINGS}")
    print(f"{'='*60}")

    if exits:
        print(f"\nEXITS ({len(exits)}):")
        for sym, reason in exits:
            print(f"  {sym:<8}  {reason}")

    if entries:
        print(f"\nENTRIES ({len(entries)}):")
        for sym in entries:
            print(f"  {sym:<8}  added")

    if not exits and not entries:
        print("\nNo changes this run.")

    print(f"\nActive holdings ({len(holdings)}):")
    _print_holdings(holdings)
    print()


if __name__ == "__main__":
    main()
