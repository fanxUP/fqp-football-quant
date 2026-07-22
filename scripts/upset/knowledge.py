"""Time-bounded league, team, and player knowledge profiles."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from psycopg2.extras import Json, RealDictCursor

KNOWLEDGE_VERSION = "upset-knowledge-v1"


def confidence_for_sample(sample_size: int, target_size: int = 30) -> float:
    return round(min(max(sample_size, 0) / target_size, 1.0), 6)


def decay_confidence(
    confidence: float,
    *,
    age_days: int,
    half_life_days: int = 180,
) -> float:
    if half_life_days <= 0:
        raise ValueError("置信度半衰期必须大于0")
    return round(float(confidence) * math.pow(0.5, max(age_days, 0) / half_life_days), 6)


def _replace_profile(
    conn: Any,
    *,
    table: str,
    identity: dict[str, Any],
    values: dict[str, Any],
) -> None:
    clauses = []
    params: list[Any] = []
    for key, value in identity.items():
        clauses.append(f"{key} IS NOT DISTINCT FROM %s")
        params.append(value)
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {table} WHERE {' AND '.join(clauses)}", params)
        all_values = {**identity, **values}
        columns = ", ".join(all_values)
        placeholders = ", ".join(["%s"] * len(all_values))
        cur.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            list(all_values.values()),
        )


def refresh_league_profiles(conn: Any, start: date, end: date) -> int:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT match.league_name, competition.id AS competition_id,
                   COUNT(*) AS sample_size,
                   AVG(result.full_home_goals + result.full_away_goals) AS avg_goals,
                   AVG((result.full_home_goals > result.full_away_goals)::int) AS home_win_rate,
                   AVG((result.full_home_goals = result.full_away_goals)::int) AS draw_rate,
                   AVG((result.full_home_goals < result.full_away_goals)::int) AS away_win_rate,
                   COUNT(event.id) AS upset_count,
                   COUNT(event.id) FILTER (WHERE event.upset_level IN ('S','A'))
                       AS severe_upset_count,
                   ARRAY_AGG(DISTINCT match.id ORDER BY match.id) AS source_ids
            FROM official_matches match
            JOIN official_results result ON result.match_id = match.id
            LEFT JOIN upset_events event ON event.match_id = match.id
            LEFT JOIN LATERAL (
                SELECT id FROM competitions candidate
                WHERE candidate.competition_name_cn = match.league_name
                ORDER BY candidate.id LIMIT 1
            ) competition ON true
            WHERE match.business_date BETWEEN %s AND %s
              AND result.result_status IN ('final','confirmed')
            GROUP BY match.league_name, competition.id
            ORDER BY match.league_name
            """,
            (start, end),
        )
        rows = [dict(row) for row in cur.fetchall()]
    for row in rows:
        sample = int(row["sample_size"])
        metrics = {
            "avg_goals": float(row["avg_goals"] or 0),
            "home_win_rate": float(row["home_win_rate"] or 0),
            "draw_rate": float(row["draw_rate"] or 0),
            "away_win_rate": float(row["away_win_rate"] or 0),
            "upset_count": int(row["upset_count"] or 0),
            "upset_rate": int(row["upset_count"] or 0) / sample if sample else 0,
            "severe_upset_count": int(row["severe_upset_count"] or 0),
        }
        _replace_profile(
            conn,
            table="league_knowledge_profiles",
            identity={
                "league_name": row["league_name"],
                "season_id": None,
                "window_start": start,
                "window_end": end,
                "knowledge_version": KNOWLEDGE_VERSION,
            },
            values={
                "competition_id": row["competition_id"],
                "valid_from": start,
                "valid_to": end,
                "sample_size": sample,
                "metrics_json": Json(metrics),
                "summary_json": Json(
                    {
                        "text": "统计画像，仅描述当前窗口，不推断因果。",
                        "status": "observed",
                    }
                ),
                "source_snapshot_ids_json": Json(row["source_ids"][:500]),
                "confidence": confidence_for_sample(sample),
            },
        )
    return len(rows)


def refresh_team_profiles(conn: Any, start: date, end: date) -> int:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH mapped AS (
                SELECT match.id, match.business_date, result.full_home_goals,
                       result.full_away_goals, event.id AS upset_event_id,
                       home_alias.team_id AS home_team_id,
                       away_alias.team_id AS away_team_id
                FROM official_matches match
                JOIN official_results result ON result.match_id = match.id
                LEFT JOIN upset_events event ON event.match_id = match.id
                LEFT JOIN team_aliases home_alias
                  ON home_alias.source_name='sporttery'
                 AND home_alias.alias_name=match.home_team_name
                LEFT JOIN team_aliases away_alias
                  ON away_alias.source_name='sporttery'
                 AND away_alias.alias_name=match.away_team_name
                WHERE match.business_date BETWEEN %s AND %s
                  AND result.result_status IN ('final','confirmed')
            ), team_matches AS (
                SELECT id, home_team_id AS team_id, true AS is_home,
                       full_home_goals AS goals_for, full_away_goals AS goals_against,
                       upset_event_id FROM mapped WHERE home_team_id IS NOT NULL
                UNION ALL
                SELECT id, away_team_id, false, full_away_goals, full_home_goals,
                       upset_event_id FROM mapped WHERE away_team_id IS NOT NULL
            )
            SELECT team_id, COUNT(*) AS sample_size,
                   AVG(goals_for) AS avg_goals_for,
                   AVG(goals_against) AS avg_goals_against,
                   AVG((goals_for > goals_against)::int) AS win_rate,
                   AVG((goals_for = goals_against)::int) AS draw_rate,
                   AVG(is_home::int) AS home_share,
                   COUNT(upset_event_id) AS upset_involved_count,
                   ARRAY_AGG(DISTINCT id ORDER BY id) AS source_ids
            FROM team_matches GROUP BY team_id ORDER BY team_id
            """,
            (start, end),
        )
        rows = [dict(row) for row in cur.fetchall()]
    for row in rows:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT season_profile.competition_season_id,
                       season.competition_id, season.season_id,
                       season_profile.manager_name
                FROM team_season_profiles season_profile
                JOIN competition_seasons season
                  ON season.id = season_profile.competition_season_id
                WHERE season_profile.team_id = %s
                  AND season_profile.snapshot_time < %s
                ORDER BY season_profile.snapshot_time DESC, season_profile.id DESC
                LIMIT 1
                """,
                (row["team_id"], end + timedelta(days=1)),
            )
            season = dict(cur.fetchone() or {})
        sample = int(row["sample_size"])
        metrics = {
            "avg_goals_for": float(row["avg_goals_for"] or 0),
            "avg_goals_against": float(row["avg_goals_against"] or 0),
            "win_rate": float(row["win_rate"] or 0),
            "draw_rate": float(row["draw_rate"] or 0),
            "home_share": float(row["home_share"] or 0),
            "upset_involved_count": int(row["upset_involved_count"] or 0),
        }
        _replace_profile(
            conn,
            table="team_knowledge_profiles",
            identity={
                "team_id": row["team_id"],
                "competition_id": season.get("competition_id"),
                "season_id": season.get("season_id"),
                "valid_from": start,
                "knowledge_version": KNOWLEDGE_VERSION,
            },
            values={
                "coach_name": season.get("manager_name"),
                "valid_to": end,
                "window_start": start,
                "window_end": end,
                "sample_size": sample,
                "metrics_json": Json(metrics),
                "summary_json": Json(
                    {"text": "球队窗口统计，不把相关性描述为因果。", "status": "observed"}
                ),
                "source_snapshot_ids_json": Json(row["source_ids"][:500]),
                "confidence": confidence_for_sample(sample),
            },
        )
    return len(rows)


def refresh_player_profiles(conn: Any, start: date, end: date) -> int:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH player_stats AS (
                SELECT player.player_id, lineup.team_id,
                       COUNT(DISTINCT lineup.match_id) AS sample_size,
                       AVG(player.is_starting::int) AS start_rate,
                       AVG(player.key_player_score) AS key_player_score,
                       MODE() WITHIN GROUP (
                           ORDER BY COALESCE(player.tactical_role, player.position)
                       ) AS tactical_role,
                       ARRAY_AGG(DISTINCT lineup.id ORDER BY lineup.id) AS source_ids
                FROM match_lineup_players player
                JOIN match_lineup_snapshots lineup ON lineup.id = player.lineup_snapshot_id
                JOIN official_matches match ON match.id = lineup.match_id
                WHERE match.business_date BETWEEN %s AND %s
                  AND lineup.snapshot_time < match.kickoff_time
                GROUP BY player.player_id, lineup.team_id
            )
            SELECT stats.*, availability.availability_status,
                   availability.replacement_quality_score,
                   availability.absence_impact_score,
                   availability.expected_return_date
            FROM player_stats stats
            LEFT JOIN LATERAL (
                SELECT snapshot.availability_status,
                       snapshot.replacement_quality_score,
                       snapshot.absence_impact_score,
                       snapshot.expected_return_date
                FROM player_availability_snapshots snapshot
                WHERE snapshot.player_id=stats.player_id
                  AND snapshot.team_id=stats.team_id
                  AND snapshot.snapshot_time < %s
                ORDER BY snapshot.snapshot_time DESC, snapshot.id DESC LIMIT 1
            ) availability ON true
            ORDER BY stats.player_id, stats.team_id
            """,
            (start, end, end + timedelta(days=1)),
        )
        rows = [dict(row) for row in cur.fetchall()]
    for row in rows:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT season.season_id
                FROM team_season_profiles profile
                JOIN competition_seasons season ON season.id=profile.competition_season_id
                WHERE profile.team_id=%s AND profile.snapshot_time < %s
                ORDER BY profile.snapshot_time DESC, profile.id DESC LIMIT 1
                """,
                (row["team_id"], end + timedelta(days=1)),
            )
            season_row = cur.fetchone()
        sample = int(row["sample_size"])
        metrics = {
            "start_rate": float(row["start_rate"] or 0),
            "key_player_score": (
                float(row["key_player_score"]) if row["key_player_score"] is not None else None
            ),
            "availability_status": row["availability_status"],
            "replacement_quality_score": (
                float(row["replacement_quality_score"])
                if row["replacement_quality_score"] is not None
                else None
            ),
            "absence_impact_score": (
                float(row["absence_impact_score"])
                if row["absence_impact_score"] is not None
                else None
            ),
            "expected_return_date": (
                row["expected_return_date"].isoformat()
                if row["expected_return_date"] is not None
                else None
            ),
        }
        _replace_profile(
            conn,
            table="player_knowledge_profiles",
            identity={
                "player_id": row["player_id"],
                "team_id": row["team_id"],
                "season_id": season_row[0] if season_row else None,
                "valid_from": start,
                "knowledge_version": KNOWLEDGE_VERSION,
            },
            values={
                "valid_to": end,
                "window_start": start,
                "window_end": end,
                "tactical_role": row["tactical_role"],
                "sample_size": sample,
                "metrics_json": Json(metrics),
                "summary_json": Json(
                    {"text": "球员画像仅基于已确认赛前阵容。", "status": "observed"}
                ),
                "source_snapshot_ids_json": Json(row["source_ids"][:500]),
                "confidence": confidence_for_sample(sample),
            },
        )
    return len(rows)


def decay_stale_profiles(conn: Any, as_of: date) -> None:
    """Recalculate old-profile confidence from sample size, never cumulatively."""
    for table in (
        "league_knowledge_profiles",
        "team_knowledge_profiles",
        "player_knowledge_profiles",
    ):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {table}
                SET confidence = LEAST(sample_size / 30.0, 1.0)
                    * POWER(0.5, GREATEST(%s - valid_to, 0) / 180.0)
                WHERE valid_to IS NOT NULL
                """,
                (as_of,),
            )


def refresh_knowledge(
    conn: Any,
    *,
    end: date,
    window_days: int = 180,
) -> dict[str, Any]:
    start = end - timedelta(days=window_days - 1)
    counts = {
        "leagues": refresh_league_profiles(conn, start, end),
        "teams": refresh_team_profiles(conn, start, end),
        "players": refresh_player_profiles(conn, start, end),
    }
    decay_stale_profiles(conn, end)
    conn.commit()
    return {"window_start": start.isoformat(), "window_end": end.isoformat(), **counts}
