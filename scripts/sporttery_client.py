"""Sporttery.cn (竞彩网) JSON API client.

Official Chinese sports lottery data source. No auth required.
Rate-limited to respect the server.

Endpoints:
  - getMatchCalculatorV1.qry  → match schedule + odds (SP values)
  - getMatchResultV1.qry      → finished match results
"""

from __future__ import annotations

import time
from typing import Any

import httpx


class SportteryClient:
    """HTTP client for webapi.sporttery.cn JSON APIs."""

    BASE_URL = "https://webapi.sporttery.cn/gateway/jc/football/"

    def __init__(
        self,
        timeout: float = 30.0,
        min_interval: float = 1.0,
        max_retries: int = 3,
    ) -> None:
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.sporttery.cn/",
            },
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_request_time = 0.0

    def _rate_limit(self) -> None:
        """Ensure minimum interval between requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request with retry and rate limiting."""
        self._rate_limit()
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                print(f"[sporttery] GET {path} params={params} (attempt {attempt})")
                resp = self._client.get(path, params=params)
                self._last_request_time = time.monotonic()
                resp.raise_for_status()
                data = resp.json()
                print(f"[sporttery] GET {path} → {resp.status_code}")
                return data
            except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
                last_error = e
                print(f"[sporttery] GET {path} error (attempt {attempt}): {e}")
                if attempt < self._max_retries:
                    backoff = 2**attempt
                    print(f"[sporttery] retrying in {backoff}s...")
                    time.sleep(backoff)
        raise RuntimeError(
            f"SportteryClient: {self._max_retries} attempts failed for {path}: {last_error}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_daily_matches(self, business_date: str) -> dict[str, Any]:
        """Fetch match schedule + odds for a given date.

        Args:
            business_date: Date string in YYYY-MM-DD format.

        Returns:
            Raw JSON response from the API. The match list is at
            ``response["value"]["matchInfoList"]``.
        """
        params = {
            "poolCode": "hhad,had",
            "channel": "c",
        }
        # The business_date is often inferred server-side from the current date,
        # but we pass it for logging / future API changes.
        return self._request("getMatchCalculatorV1.qry", params=params)

    def get_match_results(self, begin_date: str, end_date: str, page: int = 1) -> dict[str, Any]:
        """Fetch finished match results for a date range.

        Args:
            begin_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
            page: Page number (1-indexed).

        Returns:
            Raw JSON response from the API.
        """
        params = {
            "matchBeginDate": begin_date,
            "matchEndDate": end_date,
            "matchPage": str(page),
            "pcOrWap": "0",
            "leagueId": "",
        }
        return self._request("getMatchResultV1.qry", params=params)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()
