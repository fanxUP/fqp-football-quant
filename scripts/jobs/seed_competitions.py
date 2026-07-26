"""Seed competitions, seasons, competition_seasons from API-Football.

One-shot script to populate the enrichment pipeline's base data.
Safe to re-run: uses ON CONFLICT DO NOTHING / UPDATE.
"""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db

# ── API-Football league ID → internal mapping ──
LEAGUE_MAP: list[dict[str, Any]] = [
    {
        "api_league_id": 71,
        "competition_code": "apifootball:71",
        "competition_name_cn": "巴西甲级联赛",
        "competition_name_en": "Serie A",
        "country": "Brazil",
        "competition_type": "league",
        "is_cup": False,
        "is_league": True,
        "season_code": "apifootball:71:2026",
        "season_name": "2026赛季",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "is_current": True,
        "total_teams": 20,
        "stage_format": "double_round_robin",
    },
    {
        "api_league_id": 2,
        "competition_code": "apifootball:2",
        "competition_name_cn": "欧洲冠军联赛",
        "competition_name_en": "UEFA Champions League",
        "country": "World",
        "competition_type": "cup",
        "is_cup": True,
        "is_league": False,
        "has_group_stage": True,
        "has_knockout_stage": True,
        "season_code": "apifootball:2:2026",
        "season_name": "2026/27赛季",
        "start_date": "2026-07-01",
        "end_date": "2027-06-30",
        "is_current": True,
        "total_teams": 36,
        "stage_format": "league_and_knockout",
    },
    {
        "api_league_id": 253,
        "competition_code": "apifootball:253",
        "competition_name_cn": "美国职业大联盟",
        "competition_name_en": "Major League Soccer",
        "country": "USA",
        "competition_type": "league",
        "is_cup": False,
        "is_league": True,
        "season_code": "apifootball:253:2026",
        "season_name": "2026赛季",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "is_current": True,
        "total_teams": 30,
        "stage_format": "regular_season_and_playoffs",
    },
    {
        "api_league_id": 103,
        "competition_code": "apifootball:103",
        "competition_name_cn": "挪威超级联赛",
        "competition_name_en": "Eliteserien",
        "country": "Norway",
        "competition_type": "league",
        "is_cup": False,
        "is_league": True,
        "season_code": "apifootball:103:2026",
        "season_name": "2026赛季",
        "start_date": "2026-03-01",
        "end_date": "2026-11-30",
        "is_current": True,
        "total_teams": 16,
        "stage_format": "single_round_robin",
    },
    {
        "api_league_id": 244,
        "competition_code": "apifootball:244",
        "competition_name_cn": "芬兰超级联赛",
        "competition_name_en": "Veikkausliiga",
        "country": "Finland",
        "competition_type": "league",
        "is_cup": False,
        "is_league": True,
        "season_code": "apifootball:244:2026",
        "season_name": "2026赛季",
        "start_date": "2026-03-01",
        "end_date": "2026-11-30",
        "is_current": True,
        "total_teams": 12,
        "stage_format": "double_round_robin",
    },
    {
        "api_league_id": 113,
        "competition_code": "apifootball:113",
        "competition_name_cn": "瑞典超级联赛",
        "competition_name_en": "Allsvenskan",
        "country": "Sweden",
        "competition_type": "league",
        "is_cup": False,
        "is_league": True,
        "season_code": "apifootball:113:2026",
        "season_name": "2026赛季",
        "start_date": "2026-03-01",
        "end_date": "2026-11-30",
        "is_current": True,
        "total_teams": 16,
        "stage_format": "double_round_robin",
    },
    {
        "api_league_id": 292,
        "competition_code": "apifootball:292",
        "competition_name_cn": "韩国职业联赛",
        "competition_name_en": "K League 1",
        "country": "South Korea",
        "competition_type": "league",
        "is_cup": False,
        "is_league": True,
        "season_code": "apifootball:292:2026",
        "season_name": "2026赛季",
        "start_date": "2026-03-01",
        "end_date": "2026-11-30",
        "is_current": True,
        "total_teams": 12,
        "stage_format": "regular_season",
    },
    {
        "api_league_id": 1,
        "competition_code": "apifootball:1",
        "competition_name_cn": "世界杯",
        "competition_name_en": "World Cup",
        "country": "World",
        "competition_type": "cup",
        "is_cup": True,
        "is_league": False,
        "has_group_stage": True,
        "has_knockout_stage": True,
        "season_code": "apifootball:1:2026",
        "season_name": "2026世界杯",
        "start_date": "2026-06-11",
        "end_date": "2026-07-19",
        "is_current": True,
        "total_teams": 48,
        "stage_format": "group_and_knockout",
    },
]


def run(dry_run: bool = False) -> dict[str, Any]:
    """Seed competitions, seasons, and competition_seasons tables.

    Args:
        dry_run: if True, only print what would be done.

    Returns:
        Summary dict.
    """
    competitions_created = 0
    seasons_created = 0
    comp_seasons_created = 0

    with get_db() as conn:
        for entry in LEAGUE_MAP:
            # ── 1. Upsert competition ──
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO competitions (
                        competition_code, competition_name_cn, competition_name_en,
                        country, competition_type, is_cup, is_league,
                        has_group_stage, has_knockout_stage
                    ) VALUES (
                        %(code)s, %(cn)s, %(en)s,
                        %(country)s, %(type)s, %(is_cup)s, %(is_league)s,
                        %(has_group)s, %(has_ko)s
                    )
                    ON CONFLICT (competition_code) DO UPDATE SET
                        competition_name_cn = EXCLUDED.competition_name_cn,
                        competition_name_en = EXCLUDED.competition_name_en,
                        country = EXCLUDED.country,
                        updated_at = now()
                    RETURNING id, (xmax = 0) AS is_insert
                    """,
                    {
                        "code": entry["competition_code"],
                        "cn": entry["competition_name_cn"],
                        "en": entry["competition_name_en"],
                        "country": entry["country"],
                        "type": entry["competition_type"],
                        "is_cup": entry["is_cup"],
                        "is_league": entry["is_league"],
                        "has_group": entry.get("has_group_stage", False),
                        "has_ko": entry.get("has_knockout_stage", False),
                    },
                )
                row = cur.fetchone()
                comp_id = row[0]
                if row[1]:  # was inserted (not updated)
                    competitions_created += 1

            # ── 2. Upsert season ──
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO seasons (
                        season_code, season_name, start_date, end_date, is_current
                    ) VALUES (
                        %(code)s, %(name)s, %(start)s, %(end)s, %(current)s
                    )
                    ON CONFLICT (season_code) DO UPDATE SET
                        season_name = EXCLUDED.season_name,
                        start_date = EXCLUDED.start_date,
                        end_date = EXCLUDED.end_date,
                        is_current = EXCLUDED.is_current,
                        updated_at = now()
                    RETURNING id, (xmax = 0) AS is_insert
                    """,
                    {
                        "code": entry["season_code"],
                        "name": entry["season_name"],
                        "start": entry["start_date"],
                        "end": entry["end_date"],
                        "current": entry["is_current"],
                    },
                )
                row = cur.fetchone()
                season_id = row[0]
                if row[1]:
                    seasons_created += 1

            # ── 3. Upsert competition_season ──
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO competition_seasons (
                        competition_id, season_id, total_teams, stage_format
                    ) VALUES (
                        %(comp_id)s, %(season_id)s, %(total_teams)s, %(stage_format)s
                    )
                    ON CONFLICT (competition_id, season_id) DO UPDATE SET
                        total_teams = EXCLUDED.total_teams,
                        stage_format = EXCLUDED.stage_format,
                        updated_at = now()
                    RETURNING id, (xmax = 0) AS is_insert
                    """,
                    {
                        "comp_id": comp_id,
                        "season_id": season_id,
                        "total_teams": entry.get("total_teams"),
                        "stage_format": entry.get("stage_format"),
                    },
                )
                row = cur.fetchone()
                if row and row[1]:
                    comp_seasons_created += 1

        if not dry_run:
            conn.commit()

    return {
        "status": "ok" if not dry_run else "dry_run",
        "competitions_created": competitions_created,
        "seasons_created": seasons_created,
        "competition_seasons_created": comp_seasons_created,
    }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
