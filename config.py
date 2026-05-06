"""Central config for RICH."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()
FMP_BASE_URL = "https://financialmodelingprep.com/stable"

CACHE_DB = ROOT / "data" / "cache.db"
LOG_DIR = ROOT / "logs"
RESULTS_DIR = ROOT / "results"

TIMEZONE = "Asia/Kuala_Lumpur"
DAILY_RUN_TIME = "08:30"

FUNDAMENTAL_YEARS = 10
REQUEST_TIMEOUT_S = 20
MAX_RETRIES = 3

# Screening floors
MIN_MARKET_CAP_USD = 2_000_000_000
MIN_DAILY_DOLLAR_VOLUME = 5_000_000
MIN_HISTORICAL_YEARS = 5
PREFERRED_HISTORICAL_YEARS = 10

# Sectors excluded from the universe — these are structurally hard to score
# fairly with RICH's fundamental model (regulatory capital, rate sensitivity,
# non-standard accruals). "Financial Services" covers banks and insurance.
EXCLUDED_SECTORS: frozenset[str] = frozenset({
    "Financial Services",
    "Utilities",
    "Real Estate",
})

# Cooldown
COOLDOWN_DAYS = 60

# Output
TOP_N = 5

# Valuation
VALUATION_WEIGHT = 0.5   # k in: total_score_adj = total_score + k * valuation_adj


def require_api_key() -> str:
    if not FMP_API_KEY:
        raise RuntimeError(
            "FMP_API_KEY missing. Copy .env.example to .env and set your key."
        )
    return FMP_API_KEY
