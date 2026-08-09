"""Incrementally update Glicko-2 team ratings from settled official matches."""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.glicko2_model import update_glicko2_ratings
from scripts.team_registry import ensure_official_match_teams


def run(dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"status": "dry_run", "message": "glicko2 update (dry run)"}
    with get_db() as conn:
        teams_created = ensure_official_match_teams(conn)
        cur = conn.cursor()
        cur.execute(
            """
                SELECT m.id, home_team.id, away_team.id, DATE(m.kickoff_time)::text,
                       r.full_home_goals, r.full_away_goals, home_team.team_name_cn,
                       away_team.team_name_cn, m.league_name
                FROM official_matches m
                JOIN official_results r ON r.match_id = m.id
                JOIN LATERAL (
                    SELECT candidate.id, candidate.team_name_cn FROM teams candidate
                    WHERE candidate.team_name_cn = m.home_team_name ORDER BY candidate.id LIMIT 1
                ) home_team ON true
                JOIN LATERAL (
                    SELECT candidate.id, candidate.team_name_cn FROM teams candidate
                    WHERE candidate.team_name_cn = m.away_team_name ORDER BY candidate.id LIMIT 1
                ) away_team ON true
                LEFT JOIN glicko2_update_logs processed ON processed.match_id = m.id
                WHERE r.full_home_goals IS NOT NULL AND r.full_away_goals IS NOT NULL
                  AND m.kickoff_time < timezone('Asia/Shanghai', NOW())
                  AND processed.id IS NULL
                ORDER BY m.kickoff_time ASC, m.id ASC
            """
        )
        matches = cur.fetchall()
        updated = 0
        errors: list[dict[str, Any]] = []
        for row in matches:
            try:
                update_glicko2_ratings(
                    conn,
                    home_team_id=int(row[1]),
                    away_team_id=int(row[2]),
                    match_date=row[3],
                    home_goals=int(row[4]),
                    away_goals=int(row[5]),
                    home_team_name=str(row[6]),
                    away_team_name=str(row[7]),
                    season=row[8],
                    match_id=int(row[0]),
                )
                updated += 1
            except Exception as exc:
                conn.rollback()
                if len(errors) < 10:
                    errors.append({"match_id": row[0], "error": str(exc)})
        return {
            "status": "ok" if not errors else "partial" if updated else "error",
            "updated": updated,
            "errors": len(errors),
            "teams_created": teams_created,
            "total_matches_processed": len(matches),
            "error_samples": errors,
        }
