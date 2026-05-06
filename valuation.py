"""Valuation overlay: sector-median-PE anchor + quality/growth adjustment.

Runs after scoring, before storage. Appends six fields to each candidate dict:
    sector_median_pe, fair_value_pe, pe_vs_sector, valuation_adj, valuation_label,
    valuation_model_version

Does NOT mutate total_score, quality_score, growth_score, or value_risk_score.
Ranking is unchanged in this phase (valuation_adj is shadow-only).

Rollback: remove import + two loops from pipeline.py and delete this file.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Long-run sector median P/E reference values (static fallback, v1).
STATIC_SECTOR_PE: dict[str, float] = {
    "Technology":              28.0,
    "Healthcare":              22.0,
    "Financial Services":      14.0,
    "Consumer Cyclical":       20.0,
    "Industrials":             18.0,
    "Energy":                  12.0,
    "Utilities":               16.0,
    "Real Estate":             30.0,
    "Basic Materials":         14.0,
    "Communication Services":  20.0,
    "Consumer Defensive":      20.0,
    "_default":                18.0,
}


MODEL_VERSION = "v1_static_sector_pe"


@dataclass
class ValuationResult:
    sector_median_pe:      float | None = None
    fair_value_pe:         float | None = None
    pe_vs_sector:          float | None = None
    valuation_adj:         float        = 0.0
    valuation_label:       str          = "n/a"
    valuation_model_version: str        = MODEL_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "sector_median_pe":       self.sector_median_pe,
            "fair_value_pe":          self.fair_value_pe,
            "pe_vs_sector":           self.pe_vs_sector,
            "valuation_adj":          self.valuation_adj,
            "valuation_label":        self.valuation_label,
            "valuation_model_version": self.valuation_model_version,
        }


def _label(ratio: float) -> str:
    if ratio < 0.70:  return "deep_discount"
    if ratio < 0.90:  return "discount"
    if ratio < 1.10:  return "fair"
    if ratio < 1.40:  return "premium"
    return "expensive"


def compute_valuation(
    stock_pe:      float | None,
    quality_score: float,
    growth_score:  float,
    sector:        str | None,
) -> ValuationResult:
    """Pure computation — no I/O, no side effects.

    Returns a sentinel ValuationResult (adj=0.0, label='n/a') when stock_pe is
    missing, zero, or negative so callers never need to guard the return value.
    """
    if not isinstance(stock_pe, (int, float)) or stock_pe <= 0:
        return ValuationResult()

    sector_pe = STATIC_SECTOR_PE.get(sector or "", STATIC_SECTOR_PE["_default"])

    quality_factor = (quality_score - 50) / 50   # [-1, +1]
    growth_factor  = (growth_score  - 50) / 50
    blend          = 0.6 * quality_factor + 0.4 * growth_factor

    fair_pe    = sector_pe * (1 + 0.25 * blend)
    ratio      = stock_pe / fair_pe
    raw_adj    = (1.0 - ratio) * 15.0
    adj        = max(-10.0, min(10.0, raw_adj))

    return ValuationResult(
        sector_median_pe = round(sector_pe, 2),
        fair_value_pe    = round(fair_pe,   2),
        pe_vs_sector     = round(ratio,      3),
        valuation_adj    = round(adj,        2),
        valuation_label  = _label(ratio),
    )


def apply_valuation(candidate: dict[str, Any]) -> None:
    """Mutate candidate in-place, appending valuation overlay fields.

    Reads:
        candidate["scoring"]["quality_score"]
        candidate["scoring"]["growth_score"]
        candidate["factors"]["priceEarningsRatio"]
        candidate.get("sector")   -- set by pipeline after profile fetch

    Never raises. On any error, overlay fields are left at sentinel values.
    """
    try:
        sc = candidate["scoring"]
        result = compute_valuation(
            stock_pe      = candidate["factors"].get("priceEarningsRatio"),
            quality_score = sc["quality_score"],
            growth_score  = sc["growth_score"],
            sector        = candidate.get("sector"),
        )
    except Exception:
        result = ValuationResult()

    candidate.update(result.as_dict())
