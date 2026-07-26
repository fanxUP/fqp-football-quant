"""Build the locally bundled team-crest library from public provider assets.

The frontend must never depend on a live third-party logo URL at render time.
This script maps every current ``teams`` row (including aliases) to a 500.com
team identifier, downloads the transparent crest PNG once, and regenerates
the TypeScript registry consumed by the UI.

Run from the repository root:
    python3 scripts/jobs/build_team_icon_library.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.backend.src.db import get_db  # noqa: E402

ASSET_DIR = ROOT / "apps/frontend/public/team-crests"
REGISTRY_PATH = ROOT / "apps/frontend/src/shared/data/teamCrests.generated.ts"
ICON_URL = "https://liansai.500.com/static/soccerdata/images/TeamPic/teamsignnew_{team_id}.png"
LEAGUE_PAGE_URL = "https://liansai.500.com/zuqiu-{league_id}/"
LEAGUE_IDS = (19476, 19554, 19501, 19506, 19507)
PROVIDER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# Provider and internal naming order differ for this club.
MANUAL_PROVIDER_NAMES = {"奥斯陆KFUM": "KFUM奥斯陆"}
# Official Sporttery uses this spelling while the existing 500.com team row
# uses the reverse order.  Keep one crest entry and retain both names.
MANUAL_TEAM_NAME_ALIASES = {"KFUM奥斯陆": "奥斯陆KFUM"}


def _fetch_provider_page(url: str) -> str:
    request = urllib.request.Request(url, headers=PROVIDER_HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("gbk", errors="ignore")


def normalize_team_name(value: str) -> str:
    return re.sub(r"[\s·.。\-（）()]+", "", value).lower()


def fetch_provider_teams() -> dict[str, dict[str, str]]:
    """Return normalized 500.com team names with their stable crest IDs."""
    teams: dict[str, dict[str, str]] = {}
    pattern = re.compile(r'href="https://liansai\.500\.com/team/(\d+)/">([^<]+)</a>')
    for league_id in LEAGUE_IDS:
        html = _fetch_provider_page(f"{LEAGUE_PAGE_URL.format(league_id=league_id)}teams/")
        for provider_id, name in pattern.findall(html):
            teams[normalize_team_name(name)] = {"id": provider_id, "name": name}
    return teams


def load_database_teams() -> list[dict[str, Any]]:
    with get_db() as conn:
        with conn.cursor() as cur:
            # Official Sporttery rows carry the stable 500.com-compatible
            # team ids in raw_json.  Prefer these ids over name scraping so
            # every team in the official match history can receive a crest,
            # including teams outside the five currently tracked leagues.
            cur.execute(
                """
                SELECT team_name, provider_id
                FROM (
                    SELECT home_team_name AS team_name,
                           raw_json->>'homeTeamId' AS provider_id
                    FROM official_matches
                    WHERE home_team_name IS NOT NULL
                    UNION
                    SELECT away_team_name AS team_name,
                           raw_json->>'awayTeamId' AS provider_id
                    FROM official_matches
                    WHERE away_team_name IS NOT NULL
                ) official
                ORDER BY team_name
                """
            )
            official_rows = cur.fetchall()
            cur.execute(
                """
                SELECT t.id, t.team_name_cn, t.team_name_en, t.short_name,
                       ARRAY_REMOVE(ARRAY_AGG(ta.alias_name), NULL) AS aliases
                FROM teams t
                LEFT JOIN team_aliases ta ON ta.team_id = t.id
                GROUP BY t.id
                ORDER BY t.id
                """
            )
            database_teams = [
                {
                    "id": row[0],
                    "name_cn": row[1] or "",
                    "name_en": row[2] or "",
                    "short_name": row[3] or "",
                    "aliases": row[4] or [],
                }
                for row in cur.fetchall()
            ]
            by_name = {team["name_cn"]: team for team in database_teams if team["name_cn"]}
            for alias_name, canonical_name in MANUAL_TEAM_NAME_ALIASES.items():
                if alias_name in by_name and canonical_name in by_name:
                    alias_team = by_name.pop(alias_name)
                    canonical_team = by_name[canonical_name]
                    canonical_team["aliases"] = list(
                        dict.fromkeys(
                            [
                                *canonical_team["aliases"],
                                alias_name,
                                alias_team["name_cn"],
                                alias_team["name_en"],
                                alias_team["short_name"],
                            ]
                        )
                    )
            for team_name, provider_id in official_rows:
                canonical_name = MANUAL_TEAM_NAME_ALIASES.get(team_name, team_name)
                if canonical_name != team_name and canonical_name in by_name:
                    if team_name not in by_name[canonical_name]["aliases"]:
                        by_name[canonical_name]["aliases"].append(team_name)
                    continue
                if team_name in by_name:
                    continue
                by_name[team_name] = {
                    "id": None,
                    "name_cn": team_name,
                    "name_en": "",
                    "short_name": "",
                    "aliases": [],
                    "provider_id": provider_id,
                }
            return list(by_name.values())


def resolve_team_icons(
    database_teams: list[dict[str, Any]], provider_teams: dict[str, dict[str, str]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve each current internal team to one provider crest."""
    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for team in database_teams:
        if team.get("provider_id"):
            resolved.append(
                {
                    "names": list(
                        dict.fromkeys(
                            name
                            for name in [
                                team["name_cn"],
                                team["name_en"],
                                team["short_name"],
                                *team["aliases"],
                            ]
                            if name
                        )
                    ),
                    "logoUrl": f"/team-crests/500-{team['provider_id']}.png",
                    "source": "500com",
                    "sourceUrl": ICON_URL.format(team_id=team["provider_id"]),
                }
            )
            continue
        names = [team["name_cn"], team["name_en"], team["short_name"], *team["aliases"]]
        manual = MANUAL_PROVIDER_NAMES.get(team["name_cn"])
        if manual:
            names.append(manual)
        unique_names = list(dict.fromkeys(name for name in names if name))
        provider = next(
            (
                provider_teams.get(normalize_team_name(name))
                for name in unique_names
                if normalize_team_name(name) in provider_teams
            ),
            None,
        )
        if not provider:
            missing.append(team["name_cn"] or str(team["id"]))
            continue
        resolved.append(
            {
                "names": unique_names,
                "logoUrl": f"/team-crests/500-{provider['id']}.png",
                "source": "500com",
                "sourceUrl": ICON_URL.format(team_id=provider["id"]),
            }
        )
    return resolved, missing


def asset_extension(body: bytes) -> str:
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return ".webp"
    if body.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    raise ValueError("provider response is not a supported image")


def download_assets(entries: list[dict[str, Any]]) -> int:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for entry in {entry["sourceUrl"]: entry for entry in entries}.values():
        provider_id = entry["sourceUrl"].removesuffix(".png").rsplit("_", 1)[-1]
        existing = next(iter(ASSET_DIR.glob(f"500-{provider_id}.*")), None)
        if existing:
            logo_url = f"/team-crests/{existing.name}"
            for matching_entry in entries:
                if matching_entry["sourceUrl"] == entry["sourceUrl"]:
                    matching_entry["logoUrl"] = logo_url
            continue
        request = urllib.request.Request(entry["sourceUrl"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
        suffix = asset_extension(body)
        target = ASSET_DIR / f"500-{provider_id}{suffix}"
        if not target.exists() or target.read_bytes() != body:
            target.write_bytes(body)
            downloaded += 1
        logo_url = f"/team-crests/{target.name}"
        for matching_entry in entries:
            if matching_entry["sourceUrl"] == entry["sourceUrl"]:
                matching_entry["logoUrl"] = logo_url
    return downloaded


def write_registry(entries: list[dict[str, Any]]) -> None:
    lines = [
        "// Generated by scripts/jobs/build_team_icon_library.py. Do not edit manually.",
        "import type { TeamCrestEntry } from './teamCrests';",
        "",
        "export const GENERATED_TEAM_CREST_REGISTRY: TeamCrestEntry[] = [",
    ]
    for entry in entries:
        public_entry = {key: entry[key] for key in ("names", "logoUrl", "source")}
        lines.append(f"  {json.dumps(public_entry, ensure_ascii=False)},")
    lines.extend(["];", ""])
    REGISTRY_PATH.write_text("\n".join(lines), encoding="utf-8")


def run() -> dict[str, Any]:
    provider_teams = fetch_provider_teams()
    database_teams = load_database_teams()
    entries, missing = resolve_team_icons(database_teams, provider_teams)
    if missing:
        raise RuntimeError(f"unmapped teams: {', '.join(missing)}")
    downloaded = download_assets(entries)
    write_registry(entries)
    return {
        "status": "ok",
        "teams": len(database_teams),
        "registry_entries": len(entries),
        "unique_assets": len({entry["logoUrl"] for entry in entries}),
        "downloaded": downloaded,
    }


if __name__ == "__main__":
    print(run())
