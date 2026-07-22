"""API-Football 赛程与官方竞彩比赛的严格匹配工具。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def _fixture_kickoff(value: str, timezone_name: str) -> datetime | None:
    """将 API 的带时区时间转换为项目使用的本地无时区时间。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None)
    return parsed


def find_matching_fixture(
    match: dict[str, Any],
    fixtures: list[dict[str, Any]],
    alias_to_team_id: dict[str, int],
    *,
    timezone_name: str = "Asia/Shanghai",
    tolerance_seconds: int = 300,
) -> dict[str, Any] | None:
    """仅在联赛、开赛时间和主客队都一致时返回唯一赛程。"""
    kickoff = match.get("kickoff_time")
    if not isinstance(kickoff, datetime):
        return None
    if kickoff.tzinfo is not None:
        kickoff = kickoff.astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None)

    home_team_id = match.get("home_team_id")
    away_team_id = match.get("away_team_id")
    league_id = match.get("api_league_id")
    if not home_team_id or not away_team_id or not league_id:
        return None

    candidates: list[dict[str, Any]] = []
    for fixture in fixtures:
        if fixture.get("league", {}).get("id") != league_id:
            continue
        api_kickoff = _fixture_kickoff(
            str(fixture.get("fixture", {}).get("date") or ""), timezone_name
        )
        if api_kickoff is None or abs((api_kickoff - kickoff).total_seconds()) > tolerance_seconds:
            continue
        api_home = str(fixture.get("teams", {}).get("home", {}).get("name") or "")
        api_away = str(fixture.get("teams", {}).get("away", {}).get("name") or "")
        if alias_to_team_id.get(api_home) != home_team_id:
            continue
        if alias_to_team_id.get(api_away) != away_team_id:
            continue
        candidates.append(fixture)

    return candidates[0] if len(candidates) == 1 else None


def load_api_aliases(conn: Any) -> dict[str, int]:
    """读取 API-Football 英文队名到内部球队 ID 的已审核映射。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT alias_name, team_id
            FROM team_aliases
            WHERE source_name = 'apifootball'
            """
        )
        return {str(row[0]): int(row[1]) for row in cur.fetchall()}


def load_supported_matches(
    conn: Any,
    *,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    """读取能与 API-Football 联赛和球队标识严格对齐的在售比赛。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                m.id,
                m.home_team_name,
                m.away_team_name,
                m.kickoff_time,
                home_alias.team_id,
                away_alias.team_id,
                comp.competition_season_id,
                comp.api_league_id
            FROM official_matches m
            JOIN team_aliases home_alias
              ON home_alias.source_name = 'sporttery'
             AND home_alias.alias_name = m.home_team_name
            JOIN team_aliases away_alias
              ON away_alias.source_name = 'sporttery'
             AND away_alias.alias_name = m.away_team_name
            LEFT JOIN LATERAL (
                SELECT
                    cs.id AS competition_season_id,
                    substring(c.competition_code FROM 13)::integer AS api_league_id
                FROM competition_seasons cs
                JOIN competitions c ON c.id = cs.competition_id
                JOIN seasons s ON s.id = cs.season_id
                WHERE c.competition_name_cn = m.league_name
                  AND LEFT(c.competition_code, 12) = 'apifootball:'
                  AND m.kickoff_time::date BETWEEN s.start_date AND s.end_date
                ORDER BY s.is_current DESC, s.start_date DESC
                LIMIT 1
            ) comp ON TRUE
            WHERE m.sale_status = 'selling'
              AND m.kickoff_time >= %(start_time)s
              AND m.kickoff_time < %(end_time)s
            ORDER BY m.kickoff_time, m.id
            """,
            {"start_time": start_time, "end_time": end_time},
        )
        rows = cur.fetchall()
    return [
        {
            "id": int(row[0]),
            "home_team_name": str(row[1]),
            "away_team_name": str(row[2]),
            "kickoff_time": row[3],
            "home_team_id": int(row[4]),
            "away_team_id": int(row[5]),
            "competition_season_id": int(row[6]) if row[6] is not None else None,
            "api_league_id": int(row[7]) if row[7] is not None else None,
        }
        for row in rows
    ]
