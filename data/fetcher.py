"""FMP API client — /stable/ endpoints with retries."""
from __future__ import annotations

import logging
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import FMP_BASE_URL, MAX_RETRIES, require_api_key

log = logging.getLogger(__name__)

# (connect_timeout_s, read_timeout_s) — split so a slow-to-respond server
# can't block a worker thread indefinitely even if the TCP handshake succeeds.
DEFAULT_TIMEOUT = (10, 30)


class FMPError(RuntimeError):
    """Raised when FMP returns an unusable response."""


class FMPClient:
    """Thin wrapper around FMP's /stable/ endpoints.

    All statement endpoints use query param ``symbol=`` (not path segment).
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or require_api_key()
        self.session = requests.Session()

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{FMP_BASE_URL}{path}"
        query = {"apikey": self.api_key, **(params or {})}
        try:
            resp = self.session.get(url, params=query, timeout=DEFAULT_TIMEOUT)
        except requests.Timeout:
            log.warning("timeout fetching %s (connect=%ss read=%ss)", path, *DEFAULT_TIMEOUT)
            raise
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "Error Message" in data:
            raise FMPError(f"FMP error for {path}: {data['Error Message']}")
        return data

    def profile(self, ticker: str) -> dict[str, Any]:
        data = self._get("/profile", {"symbol": ticker})
        if not data:
            raise FMPError(f"No profile returned for {ticker}")
        return data[0]

    def quote(self, ticker: str) -> dict[str, Any]:
        data = self._get("/quote", {"symbol": ticker})
        if not data:
            raise FMPError(f"No quote returned for {ticker}")
        return data[0]

    def income_statement(self, ticker: str, years: int = 10) -> list[dict[str, Any]]:
        return self._get("/income-statement", {"symbol": ticker, "limit": years}) or []

    def balance_sheet(self, ticker: str, years: int = 10) -> list[dict[str, Any]]:
        return self._get(
            "/balance-sheet-statement", {"symbol": ticker, "limit": years}
        ) or []

    def cash_flow(self, ticker: str, years: int = 10) -> list[dict[str, Any]]:
        return self._get(
            "/cash-flow-statement", {"symbol": ticker, "limit": years}
        ) or []

    def ratios(self, ticker: str, years: int = 10) -> list[dict[str, Any]]:
        return self._get("/ratios", {"symbol": ticker, "limit": years}) or []

    def key_metrics(self, ticker: str, years: int = 10) -> list[dict[str, Any]]:
        return self._get("/key-metrics", {"symbol": ticker, "limit": years}) or []

    def financial_growth(self, ticker: str, years: int = 10) -> list[dict[str, Any]]:
        return self._get(
            "/financial-growth", {"symbol": ticker, "limit": years}
        ) or []

    def enterprise_values(self, ticker: str, years: int = 10) -> list[dict[str, Any]]:
        return self._get(
            "/enterprise-values", {"symbol": ticker, "limit": years}
        ) or []

    def historical_price(
        self, ticker: str, light: bool = True
    ) -> list[dict[str, Any]]:
        path = "/historical-price-eod/light" if light else "/historical-price-eod/full"
        return self._get(path, {"symbol": ticker}) or []

    def sp500_constituents(self) -> list[dict[str, Any]]:
        return self._get("/sp500-constituent") or []

    def company_screener(self, **filters: Any) -> list[dict[str, Any]]:
        """Pass filters as kwargs (marketCapMoreThan, country, exchange, ...)."""
        return self._get("/company-screener", filters) or []
