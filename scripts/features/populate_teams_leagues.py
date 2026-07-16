"""Auto-populate teams, team_aliases, leagues, competitions from official match data.

Reads the official_matches table (populated by Stage 2) and extracts:
  - Unique team names → teams table (08 schema) + team_aliases
  - Unique league names → leagues table (02 schema)
  - League+season combos → competitions + competition_seasons (08 schema)

Idempotent — safe to run repeatedly. Uses INSERT ... ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db


def _slugify(name: str) -> str:
    """Generate a team_code from a Chinese or English name.

    For non-ASCII names (Chinese), use the first 3 characters as an
    abbreviated code. For ASCII, use uppercase first 4 letters.
    """
    if not name:
        return "UNK"
    # If contains non-ASCII, use first 3 chars
    if any(ord(c) > 127 for c in name):
        return name[:4] if len(name) >= 4 else name
    # ASCII: uppercase, strip spaces
    slug = re.sub(r"[^a-zA-Z0-9]", "", name).upper()
    return slug[:6] if len(slug) >= 3 else slug


def _competition_code(league_name: str) -> str:
    """Build a stable code for official competitions without provider IDs."""
    digest = hashlib.sha1(league_name.strip().encode("utf-8")).hexdigest()[:12]
    return f"sporttery:{digest}"


def _upsert_competition_season(
    cur: Any,
    *,
    league_name: str,
    kickoff_time: datetime,
) -> dict[str, int]:
    """Ensure an official league and its calendar-year season are resolvable."""
    created = {"competitions_created": 0, "competition_seasons_created": 0}
    cur.execute(
        """
        SELECT id
        FROM competitions
        WHERE competition_name_cn = %s
        ORDER BY CASE WHEN LEFT(competition_code, 12) = 'apifootball:' THEN 0 ELSE 1 END, id
        LIMIT 1
        """,
        (league_name,),
    )
    row = cur.fetchone()
    if row:
        competition_id = row[0]
    else:
        is_cup = any(
            marker in league_name
            for marker in ("杯", "冠军联赛", "欧罗巴", "解放者")
        )
        cur.execute(
            """
            INSERT INTO competitions (
                competition_code, competition_name_cn, country,
                competition_type, is_cup, is_league
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (competition_code) DO UPDATE SET
                competition_name_cn = EXCLUDED.competition_name_cn,
                updated_at = now()
            RETURNING id
            """,
            (
                _competition_code(league_name),
                league_name,
                _infer_country("", league_name),
                "cup" if is_cup else "league",
                is_cup,
                not is_cup,
            ),
        )
        row = cur.fetchone()
        if not row:
            return created
        competition_id = row[0]
        created["competitions_created"] = 1

    season_code = str(kickoff_time.year)
    cur.execute("SELECT id FROM seasons WHERE season_code = %s LIMIT 1", (season_code,))
    row = cur.fetchone()
    if row:
        season_id = row[0]
    else:
        cur.execute(
            """
            INSERT INTO seasons (
                season_code, season_name, start_date, end_date, is_current
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (season_code) DO UPDATE SET updated_at = now()
            RETURNING id
            """,
            (
                season_code,
                f"{season_code}赛季",
                f"{season_code}-01-01",
                f"{season_code}-12-31",
                kickoff_time.year == datetime.now().year,
            ),
        )
        row = cur.fetchone()
        if not row:
            return created
        season_id = row[0]

    cur.execute(
        """
        INSERT INTO competition_seasons (competition_id, season_id)
        VALUES (%s, %s)
        ON CONFLICT (competition_id, season_id) DO NOTHING
        RETURNING id
        """,
        (competition_id, season_id),
    )
    if cur.fetchone():
        created["competition_seasons_created"] = 1
    return created


def populate_all() -> dict[str, Any]:
    """Run all auto-population steps. Returns summary counts."""
    result: dict[str, Any] = {
        "teams_created": 0,
        "aliases_created": 0,
        "leagues_created": 0,
        "competitions_created": 0,
        "competition_seasons_created": 0,
    }

    with get_db() as conn:
        with conn.cursor() as cur:
            # -----------------------------------------------------------
            # 1. Extract unique teams from official_matches
            # -----------------------------------------------------------
            cur.execute(
                """
                SELECT DISTINCT home_team_name, away_team_name, league_name, kickoff_time
                FROM official_matches
                """
            )
            rows = cur.fetchall()

            seen_teams: set[str] = set()
            league_set: set[str] = set()
            league_seasons: dict[tuple[str, int], datetime] = {}
            team_league_map: dict[str, str] = {}

            for home, away, league, kickoff_time in rows:
                if home:
                    seen_teams.add(home)
                    if league and home not in team_league_map:
                        team_league_map[home] = league
                if away:
                    seen_teams.add(away)
                    if league and away not in team_league_map:
                        team_league_map[away] = league
                if league:
                    league_set.add(league)
                    if isinstance(kickoff_time, datetime):
                        league_seasons.setdefault((league, kickoff_time.year), kickoff_time)

            # -----------------------------------------------------------
            # 2. Insert teams
            # -----------------------------------------------------------
            for team_name in seen_teams:
                team_code = _slugify(team_name)
                country = _infer_country(team_name, team_league_map.get(team_name, ""))

                cur.execute(
                    """
                    INSERT INTO teams (team_code, team_name_cn, team_name_en, short_name, country)
                    VALUES (%(code)s, %(cn)s, %(en)s, %(short)s, %(country)s)
                    ON CONFLICT (team_code) DO UPDATE SET
                        team_name_cn = COALESCE(teams.team_name_cn, EXCLUDED.team_name_cn),
                        team_name_en = COALESCE(teams.team_name_en, EXCLUDED.team_name_en),
                        short_name = COALESCE(teams.short_name, EXCLUDED.short_name),
                        country = CASE
                            WHEN teams.country IS NULL OR teams.country = 'Unknown'
                            THEN EXCLUDED.country
                            ELSE teams.country
                        END
                    RETURNING id, (xmax = 0) AS is_inserted
                    """,
                    {
                        "code": team_code,
                        "cn": team_name,
                        "en": None,  # We don't have English names from sporttery
                        "short": team_name[:8] if len(team_name) > 8 else team_name,
                        "country": country,
                    },
                )
                row = cur.fetchone()
                team_id = row[0] if row else None
                is_new = row[1] if row else False
                if is_new:
                    result["teams_created"] += 1

                # -------------------------------------------------------
                # 3. Insert team alias (official name → team)
                # -------------------------------------------------------
                if team_id:
                    cur.execute(
                        """
                        INSERT INTO team_aliases (team_id, source_name, alias_name, language, confidence)
                        VALUES (%(tid)s, %(src)s, %(alias)s, 'zh', 1.0)
                        ON CONFLICT (source_name, alias_name) DO NOTHING
                        RETURNING id
                        """,
                        {"tid": team_id, "src": "sporttery", "alias": team_name},
                    )
                    if cur.fetchone():
                        result["aliases_created"] += 1

            # -----------------------------------------------------------
            # 4. Insert leagues
            # -----------------------------------------------------------
            for league_name in league_set:
                cur.execute(
                    """
                    INSERT INTO leagues (canonical_name, country)
                    VALUES (%(name)s, %(country)s)
                    ON CONFLICT (canonical_name) DO NOTHING
                    RETURNING id
                    """,
                    {"name": league_name, "country": "International"},
                )
                if cur.fetchone():
                    result["leagues_created"] += 1

            # -----------------------------------------------------------
            # 5. Insert competitions and season mappings
            # -----------------------------------------------------------
            for (league_name, _year), kickoff_time in sorted(league_seasons.items()):
                created = _upsert_competition_season(
                    cur,
                    league_name=league_name,
                    kickoff_time=kickoff_time,
                )
                result["competitions_created"] += created["competitions_created"]
                result["competition_seasons_created"] += created[
                    "competition_seasons_created"
                ]

        conn.commit()

    return result


def _infer_country(team_name: str, league_name: str) -> str:
    """Infer country from known team/league mappings.

    This is a best-effort mapping for World Cup national teams.
    For club teams, the league_name helps infer the country.
    """
    # Known national team → country mapping (World Cup 2026)
    national_teams: dict[str, str] = {
        "比利时": "Belgium",
        "塞内加尔": "Senegal",
        "美国": "United States",
        "波黑": "Bosnia and Herzegovina",
        "西班牙": "Spain",
        "奥地利": "Austria",
        "葡萄牙": "Portugal",
        "克罗地亚": "Croatia",
        "瑞士": "Switzerland",
        "阿尔及利亚": "Algeria",
        "澳大利亚": "Australia",
        "埃及": "Egypt",
        "阿根廷": "Argentina",
        "佛得角": "Cape Verde",
        "哥伦比亚": "Colombia",
        "加纳": "Ghana",
    }
    if team_name in national_teams:
        return national_teams[team_name]

    # For club teams, use league country mapping
    league_country: dict[str, str] = {
        "英超": "England",
        "英冠": "England",
        "西甲": "Spain",
        "德甲": "Germany",
        "意甲": "Italy",
        "法甲": "France",
        "荷甲": "Netherlands",
        "葡超": "Portugal",
        "日职": "Japan",
        "韩职": "South Korea",
        "韩国职业联赛": "South Korea",
        "瑞典超级联赛": "Sweden",
        "挪威超级联赛": "Norway",
        "芬兰超级联赛": "Finland",
        "澳超": "Australia",
        "世界杯": "International",
        "欧洲杯": "Europe",
    }
    if league_name in league_country:
        return league_country[league_name]

    return "Unknown"


if __name__ == "__main__":
    result = populate_all()
    print(f"Teams created:       {result['teams_created']}")
    print(f"Aliases created:     {result['aliases_created']}")
    print(f"Leagues created:     {result['leagues_created']}")
    print(f"Competitions:        {result['competitions_created']}")
    print(f"Competition seasons: {result['competition_seasons_created']}")
