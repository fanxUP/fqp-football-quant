"""Small Sportmonks v3 client for current-season standings.

Sporttery remains the canonical source for official lottery fixtures. This
client is only a supplementary standings provider.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class SportmonksClient:
    BASE_URL = "https://api.sportmonks.com/v3/football"

    def __init__(self, token: str | None = None, timeout: float = 30.0) -> None:
        self._token = token or os.getenv("SPORTMONKS_API_TOKEN", "")
        if not self._token:
            raise ValueError("SPORTMONKS_API_TOKEN is required (env or constructor)")
        self._client = httpx.Client(timeout=timeout, headers={"Accept": "application/json"})

    def get_standings(self, season_id: int) -> list[dict[str, Any]]:
        response = self._client.get(
            f"{self.BASE_URL}/standings/seasons/{season_id}",
            params={"api_token": self._token, "include": "participant,details,form"},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        data = payload.get("data", [])
        return data if isinstance(data, list) else []

    def close(self) -> None:
        self._client.close()
