"""Sporttery.cn (竞彩网) JSON API client.

Official Chinese sports lottery data source. No auth required.
Rate-limited to respect the server.

Endpoints:
  - Uniform getMatchCalculatorV1.qry → current card + all five play-type odds
  - Uniform getUniformMatchResultV1.qry → finished match results
  - Uniform API (no WAF):     → match list + calculator + fixed bonus history
  - Traditional lottery:      → draw info / match pool (needs Playwright)
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Any

import httpx


class SportteryClient:
    """HTTP client for webapi.sporttery.cn JSON APIs."""

    BASE_URL = "https://webapi.sporttery.cn/gateway/jc/football/"
    UNIFORM_BASE_URL = "https://webapi.sporttery.cn/gateway/uniform/football/"
    LOTTERY_BASE_URL = "https://webapi.sporttery.cn/gateway/lottery/"

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
        self._playwright = None

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
                # Don't retry on 403 (permanent block) — let caller fall back
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 403:
                    raise RuntimeError(
                        f"SportteryClient: {path} returned 403 Forbidden"
                    ) from e
                if attempt < self._max_retries:
                    backoff = 2**attempt
                    print(f"[sporttery] retrying in {backoff}s...")
                    time.sleep(backoff)
        raise RuntimeError(
            f"SportteryClient: {self._max_retries} attempts failed for {path}: {last_error}"
        )

    def _request_url(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        referer: str | None = None,
    ) -> dict[str, Any]:
        """Make a GET request to an arbitrary URL with retry and rate limiting."""
        self._rate_limit()
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                print(f"[sporttery] GET {url} params={params} (attempt {attempt})")
                headers = {"Referer": referer} if referer else None
                resp = self._client.get(url, params=params, headers=headers)
                self._last_request_time = time.monotonic()
                resp.raise_for_status()
                data = resp.json()
                print(f"[sporttery] GET {url} → {resp.status_code}")
                return data
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_error = e
                print(f"[sporttery] GET {url} error (attempt {attempt}): {e}")
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 403:
                    raise RuntimeError(
                        f"SportteryClient: {url} returned 403 Forbidden"
                    ) from e
                if attempt < self._max_retries:
                    backoff = 2**attempt
                    print(f"[sporttery] retrying in {backoff}s...")
                    time.sleep(backoff)
            except (ValueError, json.JSONDecodeError) as e:
                # Malformed JSON — fail fast, don't retry
                raise RuntimeError(f"SportteryClient: {url} returned malformed JSON: {e}") from e
        raise RuntimeError(
            f"SportteryClient: {self._max_retries} attempts failed for {url}: {last_error}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def _require_success(data: dict[str, Any], endpoint: str) -> dict[str, Any]:
        """Reject HTTP-200 API error payloads instead of treating them as empty data."""
        error_code = data.get("errorCode")
        if error_code is not None and str(error_code) != "0":
            message = data.get("errorMessage") or data.get("message") or "unknown error"
            raise RuntimeError(f"SportteryClient: {endpoint} error {error_code}: {message}")
        return data

    def get_uniform_match_list(self) -> dict[str, Any]:
        """Fetch match list from uniform API (no WAF issues).

        Returns matches across multiple dates with oddsList + poolList.
        """
        endpoint = "getMatchListV1.qry"
        return self._require_success(
            self._request_url(
                self.UNIFORM_BASE_URL + endpoint,
                {"clientCode": "3001"},
                referer="https://www.sporttery.cn/jc/zqszsc/",
            ),
            endpoint,
        )

    def get_uniform_match_results(
        self, begin_date: str, end_date: str
    ) -> dict[str, Any]:
        """Fetch official result pages one day at a time via the Uniform API.

        Official page: https://www.lottery.gov.cn/jc/zqsgkj/
        The official result endpoint's WAF rejects wider date ranges on some
        networks. Single-day requests use the same direct Uniform client path
        as the official odds collector and preserve complete official rows.
        """
        start = date.fromisoformat(begin_date)
        end = date.fromisoformat(end_date)
        if start > end:
            raise ValueError("begin_date must not be later than end_date")

        endpoint = "getUniformMatchResultV1.qry"
        match_results: list[dict[str, Any]] = []
        current = start
        while current <= end:
            day = current.isoformat()
            page_no, pages = 1, 1
            while page_no <= pages:
                params: dict[str, Any] = {
                    "matchBeginDate": day,
                    "matchEndDate": day,
                    "leagueId": "",
                    "pageSize": 100,
                    "pageNo": page_no,
                    "isFix": 0,
                    "matchPage": 1,
                    "pcOrWap": 1,
                }
                payload = self._require_success(
                    self._request_url(
                        self.UNIFORM_BASE_URL + endpoint,
                        params,
                        referer="https://www.lottery.gov.cn/jc/zqsgkj/",
                    ),
                    endpoint,
                )
                value = payload.get("value") or {}
                match_results.extend(value.get("matchResult") or [])
                pages = max(int(value.get("pages") or 1), 1)
                page_no += 1
            current += timedelta(days=1)

        return {"errorCode": "0", "value": {"matchResult": match_results}}

    def get_uniform_match_calculator(self) -> dict[str, Any]:
        """Fetch all five current Sporttery play types and their full odds."""
        endpoint = "getMatchCalculatorV1.qry"
        return self._require_success(
            self._request_url(
                self.UNIFORM_BASE_URL + endpoint,
                {"channel": "c"},
                referer="https://www.sporttery.cn/jc/jsq/zqspf/",
            ),
            endpoint,
        )

    def get_uniform_league_list(self) -> dict[str, Any]:
        """Fetch the official league catalog and its ordered season lists."""
        endpoint = "league/getLeagueListV1.qry"
        return self._require_success(
            self._request_url(
                self.UNIFORM_BASE_URL + endpoint,
                referer="https://www.sporttery.cn/zqlszl/",
            ),
            endpoint,
        )

    def get_uniform_league_matches(
        self,
        *,
        uniform_league_id: int,
        season_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Fetch one official league-season match-result window."""
        endpoint = "league/getMatchResultV1.qry"
        params: dict[str, Any] = {
            "uniformLeagueId": uniform_league_id,
            "seasonId": season_id,
        }
        if start_date is not None:
            params["startDate"] = start_date
        if end_date is not None:
            params["endDate"] = end_date
        return self._require_success(
            self._request_url(
                self.UNIFORM_BASE_URL + endpoint,
                params,
                referer="https://www.sporttery.cn/zqlszl/",
            ),
            endpoint,
        )

    def get_uniform_fixed_bonus(self, match_id: int) -> dict[str, Any]:
        """Fetch fixed bonus (all play types + odds history) for a match.

        Args:
            match_id: Sporttery internal match ID (e.g. 2040374).

        Returns:
            Response with oddsHistory (hadList, hhadList, crsList, etc.).
        """
        return self._request_url(
            self.UNIFORM_BASE_URL + "getFixedBonusV1.qry",
            {"clientCode": "3001", "matchId": str(match_id)},
        )

    def get_traditional_lottery_draw(self) -> dict[str, Any]:
        """Fetch traditional lottery (14场/任九) draw info.

        Uses direct HTTP (handles sporttery's malformed JSON inline).
        Falls back to Playwright browser only when direct API is WAF-blocked (403).

        Returns: draw info with prizeLevelList, matchList, issue list.
        """
        params = {"isVerify": "1", "param": "90,0;91,0;98,0;99,0"}
        # Attempt 1: direct API request with JSON fix
        try:
            return self._request_url(
                self.LOTTERY_BASE_URL + "getFootBallDrawInfoV2.qry", params
            )
        except RuntimeError as e:
            msg = str(e)
            # Only fall back to browser on 403 (WAF block), not malformed JSON
            if "403" in msg:
                print("[sporttery] lottery API blocked (403), falling back to browser…")
                return self._fetch_lottery_via_browser()
            if "JSON" in msg or "malformed" in msg:
                # JSON was malformed — retry with raw HTTP + JSON fix
                return self._fetch_lottery_with_json_fix(params)
            raise

    def _fetch_lottery_with_json_fix(self, params: dict) -> dict[str, Any]:
        """Retry traditional lottery with raw HTTP and malformed JSON fix."""
        import re as _re

        self._rate_limit()
        url = self.LOTTERY_BASE_URL + "getFootBallDrawInfoV2.qry"
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._client.get(url, params=params)
                self._last_request_time = time.monotonic()
                if resp.status_code == 403:
                    raise RuntimeError("403 Forbidden")
                text = resp.text
                # Fix sporttery's malformed JSON: "key":, → "key":null,
                text = _re.sub(r'("[^"]+")\s*:\s*,', r'\1:null,', text)
                return json.loads(text)
            except (httpx.HTTPError, json.JSONDecodeError) as e:
                print(f"[sporttery] lottery JSON fix attempt {attempt} failed: {e}")
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)
        raise RuntimeError(
            f"SportteryClient: failed to fetch lottery data after {self._max_retries} attempts"
        )

    # ------------------------------------------------------------------
    # Browser-based fallbacks (WAF bypass)
    # ------------------------------------------------------------------

    def get_daily_matches(self, business_date: str) -> dict[str, Any]:
        """Fetch match schedule + odds for a given date.

        Args:
            business_date: Date string in YYYY-MM-DD format.

        Returns:
            Raw JSON response from the API. The match list is at
            ``response["value"]["matchInfoList"]``.
        """
        # The official calculator returns the current selling card across its
        # business-date groups. ``business_date`` is retained for API
        # compatibility; Sporttery infers the active card server-side.
        del business_date
        return self.get_uniform_match_calculator()

    def get_match_results(self, begin_date: str, end_date: str, page: int = 1) -> dict[str, Any]:
        """Fetch finished match results for a date range.

        Args:
            begin_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
            page: Page number (1-indexed).

        Returns:
            Raw JSON response from the API.
        """
        del page
        return self.get_uniform_match_results(begin_date, end_date)

    def _fetch_lottery_via_browser(self) -> dict[str, Any]:
        """Use Playwright Chromium to fetch traditional lottery draw data.

        WAF bypass for getFootBallDrawInfoV2.qry. Also handles the
        sporttery API bug where JSON is malformed (e.g. "key":, instead of
        "key":null,).
        """
        import re as _re

        self._rate_limit()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "Playwright not available — cannot fetch traditional lottery data. "
                "Install with: pip install playwright && playwright install chromium"
            ) from e

        print("[sporttery:browser] launching Chromium for traditional lottery data…")
        t0 = time.monotonic()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            url = (
                f"{self.LOTTERY_BASE_URL}getFootBallDrawInfoV2.qry"
                f"?isVerify=1&param=90,0;91,0;98,0;99,0"
            )

            try:
                resp = page.goto(url, timeout=30000)
                status = resp.status if resp else 0
                print(f"[sporttery:browser] GET → {status}")

                if status != 200:
                    body_text = page.evaluate("document.body.innerText") if resp else ""
                    browser.close()
                    raise RuntimeError(
                        f"Browser request returned {status}: {body_text[:200]}"
                    )

                body_text = page.evaluate("document.body.innerText")

                # Fix sporttery API bug: malformed JSON like "key":,
                body_text = _re.sub(r'("[^"]+")\s*:\s*,', r'\1:null,', body_text)

                data = json.loads(body_text)
                elapsed = int((time.monotonic() - t0) * 1000)
                print(f"[sporttery:browser] OK ({elapsed}ms)")
                browser.close()
                self._last_request_time = time.monotonic()
                return data

            except Exception:
                browser.close()
                raise

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()
