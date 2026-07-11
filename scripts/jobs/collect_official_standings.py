"""Collect standings from verified official league pages.

This first adapter intentionally supports only sources that return a stable
server-rendered table. It prints unresolved team names instead of guessing
their identity or writing partial snapshots.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from typing import Any

import httpx
import certifi
from bs4 import BeautifulSoup

from apps.backend.src.db import get_db
from scripts.feature_storage import store_season_standings_snapshot

SOURCES = {
    "norway_eliteserien": {
        "competition_name": "挪威超级联赛",
        "url": "https://www.eliteserien.no/tabell",
    },
    "finland_veikkausliiga": {
        "competition_name": "芬兰超级联赛",
        "url": "https://www.veikkausliiga.com/",
    },
    "korea_kleague1": {
        "competition_name": "韩国职业联赛",
        "url": "https://www.kleague.com/record/teamRank.do",
    },
}


def _numbers(value: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", value)]


def _fetch(url: str) -> BeautifulSoup:
    try:
        response = httpx.get(
            url,
            timeout=30,
            verify=certifi.where(),
            headers={"User-Agent": "FQP standings collector/1.0"},
        )
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except httpx.ConnectError:
        # macOS curl can use the system keychain where a Python venv may not
        # see the local proxy CA. Keep TLS verification enabled in curl.
        result = subprocess.run(
            ["curl", "--fail", "--location", "--silent", "--show-error", "--max-time", "30", "-A", "FQP standings collector/1.0", url],
            check=True,
            capture_output=True,
        )
        return BeautifulSoup(result.stdout, "html.parser")


def _fetch_kleague() -> list[dict[str, Any]]:
    response = httpx.get(
        SOURCES["korea_kleague1"]["url"],
        params={"leagueId": 1, "year": 2026, "stadium": "all", "recordType": "rank"},
        timeout=30,
        verify=certifi.where(),
        headers={"User-Agent": "FQP standings collector/1.0", "X-Requested-With": "XMLHttpRequest"},
    )
    payload = response.json()
    rows = payload.get("data", {}).get("teamRank", [])
    return [
        {
            "rank": row.get("rank"), "team_name": row.get("teamName", ""),
            "played": row.get("gameCount"), "won": row.get("winCnt"),
            "drawn": row.get("tieCnt"), "lost": row.get("lossCnt"),
            "goals_for": row.get("gainGoal"), "goals_against": row.get("lossGoal"),
            "goal_difference": row.get("gapCnt"), "points": row.get("gainPoint"),
            "raw": row,
        }
        for row in rows
    ]


def parse_norway(soup: BeautifulSoup) -> list[dict[str, Any]]:
    table = soup.find("table")
    rows = [] if table is None else table.find_all("tr")
    result = []
    for row in rows[1:]:
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
        if len(cells) < 9 or not cells[0].isdigit():
            continue
        values = _numbers(" ".join(cells[2:9]))
        if len(values) < 7:
            continue
        result.append({"rank": int(cells[0]), "team_name": cells[1].split()[0], "played": values[0],
                       "won": values[1], "drawn": values[2], "lost": values[3],
                       "goals_for": values[4], "goals_against": values[5],
                       "points": values[7] if len(values) > 7 else values[6], "raw": cells})
    return result


def parse_finland(soup: BeautifulSoup) -> list[dict[str, Any]]:
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows or "Sarjataulukko" not in rows[0].get_text(" ", strip=True):
            continue
        result = []
        for row in rows[2:]:
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if len(cells) < 5 or not cells[1].rstrip(".").isdigit():
                continue
            result.append({"rank": int(cells[1].rstrip(".")), "team_name": cells[2],
                           "points": int(cells[3]), "played": int(cells[4]), "raw": cells})
        return result
    return []


def run(source_code: str | None = None, dry_run: bool = True) -> dict[str, Any]:
    selected = [source_code] if source_code else list(SOURCES)
    reports = []
    for code in selected:
        source = SOURCES[code]
        if code == "korea_kleague1":
            rows = _fetch_kleague()
        else:
            soup = _fetch(source["url"])
            rows = parse_norway(soup) if code == "norway_eliteserien" else parse_finland(soup)
        written = 0
        unresolved = []
        if not dry_run:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT cs.id FROM competition_seasons cs
                        JOIN competitions c ON c.id=cs.competition_id
                        JOIN seasons s ON s.id=cs.season_id
                        WHERE c.competition_name_cn=%s AND s.season_code='2026'
                        """,
                        (source["competition_name"],),
                    )
                    season_row = cur.fetchone()
                    if not season_row:
                        raise RuntimeError(f"missing 2026 competition season: {source['competition_name']}")
                    competition_season_id = season_row[0]
                    snapshot_time = datetime.now().isoformat(timespec="seconds")
                    for item in rows:
                        cur.execute(
                            """
                            SELECT t.id FROM teams t
                            JOIN team_aliases ta ON ta.team_id=t.id
                            WHERE ta.source_name='official_standings' AND ta.alias_name=%s
                            LIMIT 1
                            """,
                            (item["team_name"],),
                        )
                        team_row = cur.fetchone()
                        if not team_row:
                            unresolved.append(item["team_name"])
                            continue
                        stored = dict(item)
                        stored.update({"team_id": team_row[0], "competition_season_id": competition_season_id,
                                       "snapshot_time": snapshot_time, "source_name": code,
                                       "source_confidence": 0.95})
                        store_season_standings_snapshot(conn, stored)
                        written += 1
                conn.commit()
        reports.append({"source": code, "competition": source["competition_name"],
                        "rows": len(rows), "written": written,
                        "unresolved": unresolved,
                        "teams": [r["team_name"] for r in rows],
                        "status": "dry_run" if dry_run else "written"})
    return {"status": "ok", "reports": reports, "snapshot_time": datetime.now().isoformat(timespec="seconds")}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=sorted(SOURCES))
    parser.add_argument("--write", action="store_true", help="reserved for verified team mapping")
    args = parser.parse_args()
    print(run(args.source, dry_run=not args.write))
