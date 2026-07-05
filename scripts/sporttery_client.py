"""Sporttery.cn (竞彩网) JSON API client.

Official Chinese sports lottery data source. No auth required.
Rate-limited to respect the server.

Endpoints:
  - getMatchCalculatorV1.qry  → match schedule + odds (JC API, may WAF)
  - getMatchResultV1.qry      → finished match results (may WAF)
  - Uniform API (no WAF):     → match list + fixed bonus odds
  - Traditional lottery:      → draw info / match pool (needs Playwright)
"""

from __future__ import annotations

import json
import time
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
        self, url: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a GET request to an arbitrary URL with retry and rate limiting."""
        self._rate_limit()
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                print(f"[sporttery] GET {url} params={params} (attempt {attempt})")
                resp = self._client.get(url, params=params)
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

    def get_uniform_match_list(self) -> dict[str, Any]:
        """Fetch match list from uniform API (no WAF issues).

        Returns matches across multiple dates with oddsList + poolList.
        """
        return self._request_url(
            self.UNIFORM_BASE_URL + "getMatchListV1.qry",
            {"clientCode": "3001"},
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
        # Try direct API first; fall back to browser on 403
        try:
            return self._request("getMatchResultV1.qry", params=params)
        except RuntimeError as e:
            if "403" in str(e):
                print("[sporttery] direct API blocked (403), falling back to browser…")
                return self._fetch_results_via_browser(begin_date, end_date, page)
            raise

    def _fetch_results_via_browser(
        self, begin_date: str, end_date: str, page: int = 1
    ) -> dict[str, Any]:
        """Use Playwright Chromium to fetch results when direct API is blocked.

        Navigates to the sporttery.cn results JSON endpoint with a real browser
        TLS fingerprint to bypass WAF protection.
        """
        self._rate_limit()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright not available — cannot fetch results via browser. "
                "Install with: pip install playwright && playwright install chromium"
            )

        print(f"[sporttery:browser] launching Chromium for results {begin_date}→{end_date}…")
        t0 = time.monotonic()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            url = (
                f"{self.BASE_URL}getMatchResultV1.qry"
                f"?matchBeginDate={begin_date}"
                f"&matchEndDate={end_date}"
                f"&matchPage={page}"
                f"&pcOrWap=0"
                f"&leagueId="
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

                # Extract JSON from the page body (browser renders JSON as text)
                body_text = page.evaluate("document.body.innerText")
                data = json.loads(body_text)
                elapsed = int((time.monotonic() - t0) * 1000)
                print(f"[sporttery:browser] OK ({elapsed}ms)")
                browser.close()
                self._last_request_time = time.monotonic()
                return data

            except Exception:
                browser.close()
                raise

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
        except ImportError:
            raise RuntimeError(
                "Playwright not available — cannot fetch traditional lottery data. "
                "Install with: pip install playwright && playwright install chromium"
            )

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
