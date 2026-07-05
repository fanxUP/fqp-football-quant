"""Seed competitions, seasons, competition_seasons from API-Football.

One-shot script to populate the enrichment pipeline's base data.
Safe to re-run: uses ON CONFLICT DO NOTHING / UPDATE.
"""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.api_football_client import ApiFootballClient


# ── API-Football league ID → internal mapping ──
LEAGUE_MAP: list[dict[str, Any]] = [
    {
        "api_league_id": 113,
        "competition_code": "apifootball:113",
        "competition_name_cn": "瑞典超级联赛",
        "competition_name_en": "Allsvenskan",
        "country": "Sweden",
        "competition_type": "league",
        "is_cup": False,
        "is_league": True,
        "season_code": "2026",
        "season_name": "2026赛季",
        "start_date": "2026-03-01",
        "end_date": "2026-11-30",
        "is_current": True,
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
        "season_code": "2026",
        "season_name": "2026赛季",
        "start_date": "2026-03-01",
        "end_date": "2026-11-30",
        "is_current": True,
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
        "season_code": "2026",
        "season_name": "2026世界杯",
        "start_date": "2026-06-11",
        "end_date": "2026-07-19",
        "is_current": True,
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
                        competition_id, season_id
                    ) VALUES (
                        %(comp_id)s, %(season_id)s
                    )
                    ON CONFLICT (competition_id, season_id) DO NOTHING
                    RETURNING id
                    """,
                    {"comp_id": comp_id, "season_id": season_id},
                )
                row = cur.fetchone()
                if row:
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
