"""Teams and feature-snapshot endpoints (Stage 3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db

router = APIRouter(tags=["teams"])


@router.get("/api/events/coverage")
def list_event_coverage():
    """Return source-aware data coverage for every competition season."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT competition_season_id, competition_name, season_code,
                       total_teams, official_match_count, supplemental_match_count,
                       official_standings_snapshot_count,
                       supplemental_standings_snapshot_count,
                       latest_official_standings_at,
                       latest_supplemental_standings_at,
                       mapped_supplemental_match_count,
                       unmapped_supplemental_match_count
                FROM competition_data_coverage
                ORDER BY competition_name
                """
            )
            rows = cur.fetchall()
    return {
        "coverage": [
            {
                "competition_season_id": r[0],
                "competition_name": r[1],
                "season_code": r[2],
                "total_teams": r[3],
                "official_match_count": r[4],
                "supplemental_match_count": r[5],
                "official_standings_snapshot_count": r[6],
                "supplemental_standings_snapshot_count": r[7],
                "latest_official_standings_at": r[8].isoformat() if hasattr(r[8], "isoformat") else (str(r[8]) if r[8] else None),
                "latest_supplemental_standings_at": r[9].isoformat() if hasattr(r[9], "isoformat") else (str(r[9]) if r[9] else None),
                "mapped_supplemental_match_count": r[10],
                "unmapped_supplemental_match_count": r[11],
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/api/teams")
def list_teams():
    """List known teams with alias counts and profiles."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.id, t.team_code, t.team_name_cn, t.team_name_en,
                    t.country, t.short_name,
                    COUNT(ta.id) AS alias_count,
                    COUNT(tsp.id) AS profile_count
                FROM teams t
                LEFT JOIN team_aliases ta ON ta.team_id = t.id
                LEFT JOIN team_season_profiles tsp ON tsp.team_id = t.id
                GROUP BY t.id
                ORDER BY t.team_name_cn
                """
            )
            rows = cur.fetchall()
    return {
        "teams": [
            {
                "id": r[0],
                "team_code": r[1],
                "team_name_cn": r[2],
                "team_name_en": r[3],
                "country": r[4],
                "short_name": r[5],
                "alias_count": r[6],
                "profile_count": r[7],
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ── Today's matches ───────────────────────────────────────────────


@router.get("/api/matches/today")
def list_today_matches():
    """List today's matches (kickoff_time::date = CURRENT_DATE)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.id, m.league_name, m.home_team_name, m.away_team_name,
                       m.kickoff_time, m.match_status,
                       COALESCE(m.raw_json->>'matchNumStr', m.official_match_code::text) AS match_num_str,
                       (SELECT data_completeness_score FROM match_feature_snapshots fs
                        WHERE fs.match_id = m.id ORDER BY fs.snapshot_time DESC LIMIT 1) AS completeness,
                       (SELECT COUNT(*) FROM official_odds_snapshots os
                        WHERE os.match_id = m.id) AS odds_count
                FROM official_matches m
                WHERE m.kickoff_time::date = CURRENT_DATE
                ORDER BY m.kickoff_time
            """)
            rows = cur.fetchall()
    return {
        "matches": [
            {
                "match_id": r[0],
                "league_name": r[1],
                "home_team_name": r[2],
                "away_team_name": r[3],
                "kickoff_time": r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
                "match_status": r[5],
                "match_num_str": r[6],
                "completeness": float(r[7]) if r[7] else None,
                "odds_count": r[8] or 0,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/api/matches/active")
def list_active_matches(limit: int = Query(500, ge=1, le=5000)):
    """List the official event-catalog matches that have not finished yet.

    This is deliberately broader than the betting terminal: a match remains in
    the match center after Sporttery stops selling it, until the official match
    status is final.
    """
    completed_statuses = ("finished", "settled", "completed", "cancelled", "canceled", "stopped")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id, m.league_name, m.home_team_name, m.away_team_name,
                       m.kickoff_time, m.match_status,
                       COALESCE(m.raw_json->>'matchNumStr', m.official_match_code::text) AS match_num_str
                FROM official_matches m
                WHERE LOWER(COALESCE(m.match_status, 'scheduled')) NOT IN %s
                ORDER BY m.kickoff_time ASC
                LIMIT %s
                """,
                (completed_statuses, limit),
            )
            rows = cur.fetchall()
    return {
        "matches": [
            {
                "match_id": row[0],
                "league_name": row[1],
                "home_team_name": row[2],
                "away_team_name": row[3],
                "kickoff_time": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
                "match_status": row[5],
                "match_num_str": row[6],
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.get("/api/features/snapshots")
def list_feature_snapshots(
    match_id: int | None = Query(None),
    limit: int = Query(20),
):
    """List recent feature snapshots, optionally filtered by match."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if match_id:
                cur.execute(
                    """
                    SELECT fs.id, fs.match_id, fs.snapshot_time, fs.feature_version,
                           fs.home_team_id, fs.away_team_id,
                           fs.data_completeness_score, fs.uncertainty_score,
                           fs.home_rest_days, fs.away_rest_days, fs.rest_days_diff,
                           m.home_team_name, m.away_team_name, m.league_name,
                           m.official_match_code, m.kickoff_time,
                           COALESCE(m.raw_json->>'matchNumStr', m.official_match_code::text) AS match_num_str
                    FROM match_feature_snapshots fs
                    JOIN official_matches m ON m.id = fs.match_id
                    WHERE fs.match_id = %s
                    ORDER BY fs.snapshot_time DESC LIMIT %s
                    """,
                    (match_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT fs.id, fs.match_id, fs.snapshot_time, fs.feature_version,
                           fs.home_team_id, fs.away_team_id,
                           fs.data_completeness_score, fs.uncertainty_score,
                           fs.home_rest_days, fs.away_rest_days, fs.rest_days_diff,
                           m.home_team_name, m.away_team_name, m.league_name,
                           m.official_match_code, m.kickoff_time,
                           COALESCE(m.raw_json->>'matchNumStr', m.official_match_code::text) AS match_num_str
                    FROM match_feature_snapshots fs
                    JOIN official_matches m ON m.id = fs.match_id
                    ORDER BY fs.snapshot_time DESC LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
    return {
        "snapshots": [
            {
                "id": r[0],
                "match_id": r[1],
                "snapshot_time": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
                "feature_version": r[3],
                "home_team_id": r[4],
                "away_team_id": r[5],
                "data_completeness_score": float(r[6]) if r[6] else None,
                "uncertainty_score": float(r[7]) if r[7] else None,
                "home_rest_days": r[8],
                "away_rest_days": r[9],
                "rest_days_diff": r[10],
                "home_team_name": r[11],
                "away_team_name": r[12],
                "league_name": r[13],
                "official_match_code": r[14],
                "kickoff_time": r[15].isoformat() if hasattr(r[15], "isoformat") else str(r[15]) if r[15] else None,
                "match_num_str": r[16],
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ── Events (tournament/league center) ─────────────────────────────


@router.get("/api/events")
def list_events():
    """List all leagues/tournaments with match counts (仅体彩官网数据)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT league_name, COUNT(*) AS match_count,
                       MIN(kickoff_time) AS first_match,
                       MAX(kickoff_time) AS last_match
                FROM official_matches
                WHERE raw_json->>'source' IS DISTINCT FROM '500.com'
                GROUP BY league_name
                ORDER BY MAX(kickoff_time) DESC
            """)
            rows = cur.fetchall()
    return {
        "events": [
            {
                "league_name": r[0],
                "match_count": r[1],
                "first_match": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
                "last_match": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/api/events/catalog")
def list_event_catalog(
    source: str = Query("all", pattern="^(official|supplemental|all)$"),
    league_name: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """Browse the source-labelled official/supplemental match catalog."""
    conditions = []
    params: list[Any] = []
    if source != "all":
        conditions.append("source = %s")
        params.append(source)
    if league_name:
        conditions.append("league_name = %s")
        params.append(league_name)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT source, source_row_id, source_match_code,
                       competition_season_id, home_team_id, away_team_id,
                       league_name, home_team_name, away_team_name,
                       kickoff_time, match_status, full_home_goals, full_away_goals
                FROM event_match_catalog
                {where}
                ORDER BY kickoff_time DESC
                LIMIT %s
                """,
                (*params, limit),
            )
            rows = cur.fetchall()
    return {
        "source": source,
        "matches": [
            {
                "source": r[0],
                "source_row_id": r[1],
                "source_match_code": r[2],
                "competition_season_id": r[3],
                "home_team_id": r[4],
                "away_team_id": r[5],
                "league_name": r[6],
                "home_team_name": r[7],
                "away_team_name": r[8],
                "kickoff_time": r[9].isoformat() if hasattr(r[9], "isoformat") else str(r[9]),
                "match_status": r[10],
                "ft_home_goals": r[11],
                "ft_away_goals": r[12],
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/api/events/{league_name}")
def list_event_matches(league_name: str):
    """List all matches for a specific league (仅体彩官网数据)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.id, m.home_team_name, m.away_team_name, m.kickoff_time,
                       m.match_status,
                       COALESCE(m.raw_json->>'matchNumStr', m.official_match_code::text) AS match_num_str,
                       COALESCE(r.full_home_goals, (m.raw_json->>'hscore')::int) AS full_home_goals,
                       COALESCE(r.full_away_goals, (m.raw_json->>'gscore')::int) AS full_away_goals
                FROM official_matches m
                LEFT JOIN official_results r ON r.match_id = m.id
                WHERE m.league_name = %s
                  AND m.raw_json->>'source' IS DISTINCT FROM '500.com'
                ORDER BY m.kickoff_time DESC
            """, (league_name,))
            rows = cur.fetchall()
    return {
        "league_name": league_name,
        "matches": [
            {
                "match_id": r[0],
                "home_team_name": r[1],
                "away_team_name": r[2],
                "kickoff_time": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
                "match_status": r[4],
                "match_num_str": r[5],
                "ft_home_goals": r[6] if len(r) > 6 else None,
                "ft_away_goals": r[7] if len(r) > 7 else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ── Match detail ──────────────────────────────────────────────


@router.get("/api/matches/{match_id}/detail")
def get_match_detail(match_id: int):
    """Comprehensive match detail for the Events Center drawer."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # 1. Basic match info + scores + team IDs
            cur.execute("""
                SELECT
                    m.id, m.league_name, m.home_team_name, m.away_team_name,
                    m.kickoff_time, m.match_status, m.sale_status,
                    r.half_home_goals, r.half_away_goals,
                    r.full_home_goals, r.full_away_goals,
                    r.spf_result, r.result_status,
                    ht.id AS home_team_id, ht.team_name_cn AS home_name_cn,
                    ht.team_name_en AS home_name_en, ht.short_name AS home_short,
                    ht.country AS home_country,
                    at.id AS away_team_id, at.team_name_cn AS away_name_cn,
                    at.team_name_en AS away_name_en, at.short_name AS away_short,
                    at.country AS away_country
                FROM official_matches m
                LEFT JOIN official_results r ON r.match_id = m.id
                LEFT JOIN teams ht ON ht.team_name_cn = m.home_team_name
                                   OR ht.team_name_en = m.home_team_name
                LEFT JOIN teams at ON at.team_name_cn = m.away_team_name
                                   OR at.team_name_en = m.away_team_name
                WHERE m.id = %s
            """, (match_id,))
            row = cur.fetchone()
            if not row:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Match not found")

            match_data = {
                "id": row[0],
                "league_name": row[1],
                "home_team_name": row[2],
                "away_team_name": row[3],
                "kickoff_time": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
                "match_status": row[5],
                "sale_status": row[6],
            }
            scores = None
            if any(row[i] is not None for i in (7, 8, 9, 10)):
                scores = {
                    "ht_home": row[7],
                    "ht_away": row[8],
                    "ft_home": row[9],
                    "ft_away": row[10],
                    "spf_result": row[11],
                    "result_status": row[12],
                }
            home_team_id = row[13]
            away_team_id = row[18]
            teams_data = {
                "home": {
                    "id": home_team_id,
                    "name_cn": row[14] or row[2],
                    "name_en": row[15],
                    "short_name": row[16],
                    "country": row[17],
                    "logo_url": "",
                },
                "away": {
                    "id": away_team_id,
                    "name_cn": row[19] or row[3],
                    "name_en": row[20],
                    "short_name": row[21],
                    "country": row[22],
                    "logo_url": "",
                },
            }

            # 2. Latest feature snapshot
            cur.execute("""
                SELECT data_completeness_score, uncertainty_score,
                       home_rest_days, away_rest_days, rest_days_diff,
                       home_lineup_strength_score, away_lineup_strength_score,
                       lineup_strength_diff, home_absence_impact_score,
                       away_absence_impact_score, absence_impact_diff,
                       home_motivation_score, away_motivation_score,
                       motivation_diff, temperature_2m, precipitation,
                       wind_speed_10m, weather_impact_score,
                       away_travel_distance_km, away_travel_fatigue_score,
                       stadium_id
                FROM match_feature_snapshots
                WHERE match_id = %s
                ORDER BY snapshot_time DESC LIMIT 1
            """, (match_id,))
            fs = cur.fetchone()
            feature_snapshot = None
            if fs:
                feature_snapshot = {
                    "completeness_score": float(fs[0]) if fs[0] else None,
                    "uncertainty_score": float(fs[1]) if fs[1] else None,
                    "home_rest_days": fs[2],
                    "away_rest_days": fs[3],
                    "rest_days_diff": fs[4],
                    "home_lineup_strength": float(fs[5]) if fs[5] else None,
                    "away_lineup_strength": float(fs[6]) if fs[6] else None,
                    "lineup_strength_diff": float(fs[7]) if fs[7] else None,
                    "home_absence_impact": float(fs[8]) if fs[8] else None,
                    "away_absence_impact": float(fs[9]) if fs[9] else None,
                    "absence_impact_diff": float(fs[10]) if fs[10] else None,
                    "home_motivation": float(fs[11]) if fs[11] else None,
                    "away_motivation": float(fs[12]) if fs[12] else None,
                    "motivation_diff": float(fs[13]) if fs[13] else None,
                    "temperature": float(fs[14]) if fs[14] else None,
                    "precipitation": float(fs[15]) if fs[15] else None,
                    "wind_speed": float(fs[16]) if fs[16] else None,
                    "weather_impact": float(fs[17]) if fs[17] else None,
                    "travel_distance_km": float(fs[18]) if fs[18] else None,
                    "travel_fatigue": float(fs[19]) if fs[19] else None,
                    "stadium_id": fs[20],
                }

            # 3. Predictions (latest per model)
            cur.execute("""
                SELECT DISTINCT ON (mv.model_name)
                    mv.model_name, mp.play_type, mp.option_code,
                    mp.model_probability, mp.market_probability, mp.fair_odds, mp.ev,
                    mp.confidence_score, mp.predict_time
                FROM model_predictions mp
                JOIN model_versions mv ON mv.id = mp.model_version_id
                WHERE mp.match_id = %s
                ORDER BY mv.model_name, mp.predict_time DESC
            """, (match_id,))
            pred_rows = cur.fetchall()
            predictions = None
            best_model = None
            best_ev = -999.0
            best_option = None
            if pred_rows:
                models = []
                for pr in pred_rows:
                    models.append({
                        "model_name": pr[0],
                        "play_type": pr[1],
                        "option_code": pr[2],
                        "model_probability": float(pr[3]) if pr[3] else None,
                        "market_probability": float(pr[4]) if pr[4] else None,
                        "fair_odds": float(pr[5]) if pr[5] else None,
                        "ev": float(pr[6]) if pr[6] else None,
                        "confidence": float(pr[7]) if pr[7] else None,
                        "predict_time": pr[8].isoformat() if hasattr(pr[8], "isoformat") else str(pr[8]),
                    })
                    if pr[6] and float(pr[6]) > best_ev:
                        best_ev = float(pr[6])
                        best_model = pr[0]
                        best_option = pr[2]
                predictions = {
                    "models": models,
                    "best_ev_model": best_model,
                    "best_ev_option": best_option,
                }

            # 4. Lineups
            lineups: dict[str, dict[str, Any] | None] = {"home": None, "away": None}
            for side, tid in [("home", home_team_id), ("away", away_team_id)]:
                if not tid:
                    continue
                cur.execute("""
                    SELECT mls.id, mls.formation, mls.lineup_strength_score,
                           mls.starting_11_market_value, mls.starting_11_key_player_count,
                           mls.lineup_type
                    FROM match_lineup_snapshots mls
                    WHERE mls.match_id = %s AND mls.team_id = %s
                    ORDER BY mls.snapshot_time DESC LIMIT 1
                """, (match_id, tid))
                ls = cur.fetchone()
                if not ls:
                    continue
                cur.execute("""
                    SELECT mlp.player_id, mlp.is_starting, mlp.is_substitute,
                           mlp.position, mlp.tactical_role,
                           p.player_name_cn, p.player_name_en, p.primary_position
                    FROM match_lineup_players mlp
                    LEFT JOIN players p ON p.id = mlp.player_id
                    WHERE mlp.lineup_snapshot_id = %s
                    ORDER BY mlp.is_starting DESC, mlp.id
                """, (ls[0],))
                players = [
                    {
                        "player_id": pl[0],
                        "is_starting": pl[1],
                        "is_substitute": pl[2],
                        "position": pl[3],
                        "tactical_role": pl[4],
                        "name_cn": pl[5],
                        "name_en": pl[6],
                        "primary_position": pl[7],
                    }
                    for pl in cur.fetchall()
                ]
                lineups[side] = {
                    "formation": ls[1],
                    "strength_score": float(ls[2]) if ls[2] else None,
                    "starting_11_value": float(ls[3]) if ls[3] else None,
                    "key_player_count": ls[4],
                    "lineup_type": ls[5],
                    "players": players,
                }

            # 5. Head-to-head (last 10 matches between these teams)
            h2h_all = []
            h2h_matches = []
            h2h_wins = {"home": 0, "draws": 0, "away": 0}
            if home_team_id and away_team_id:
                cur.execute("""
                    SELECT m.kickoff_time, m.home_team_name, m.away_team_name,
                           r.full_home_goals, r.full_away_goals, m.league_name
                    FROM official_matches m
                    LEFT JOIN official_results r ON r.match_id = m.id
                    WHERE ((m.home_team_name = %s AND m.away_team_name = %s)
                       OR (m.home_team_name = %s AND m.away_team_name = %s))
                      AND LOWER(m.match_status) = 'settled'
                    ORDER BY m.kickoff_time DESC
                """, (row[2], row[3], row[3], row[2]))
                h2h_all = cur.fetchall()
                for h in h2h_all:
                    if h[3] is not None and h[4] is not None:
                        if h[3] > h[4]:
                            if h[1] == row[2]:
                                h2h_wins["home"] += 1
                            else:
                                h2h_wins["away"] += 1
                        elif h[3] == h[4]:
                            h2h_wins["draws"] += 1
                    h2h_matches.append({
                        "date": h[0].isoformat() if hasattr(h[0], "isoformat") else str(h[0]),
                        "home": h[1], "away": h[2],
                        "home_goals": h[3], "away_goals": h[4],
                        "league": h[5],
                    })
                h2h_matches = h2h_matches[:10]

            h2h = {
                "total_matches": len(h2h_all) if (home_team_id and away_team_id) else 0,
                "home_wins": h2h_wins["home"],
                "draws": h2h_wins["draws"],
                "away_wins": h2h_wins["away"],
                "recent_matches": h2h_matches,
            }

            # 6. Recent form (last 5 matches per team)
            form: dict[str, list[dict[str, Any]]] = {"home": [], "away": []}
            for side_name, team_name in [("home", row[2]), ("away", row[3])]:
                cur.execute("""
                    SELECT m.kickoff_time, m.home_team_name, m.away_team_name,
                           r.full_home_goals, r.full_away_goals, m.league_name
                    FROM official_matches m
                    LEFT JOIN official_results r ON r.match_id = m.id
                    WHERE (m.home_team_name = %s OR m.away_team_name = %s)
                      AND m.id != %s
                      AND LOWER(m.match_status) = 'settled'
                    ORDER BY m.kickoff_time DESC LIMIT 5
                """, (team_name, team_name, match_id))
                for fm in cur.fetchall():
                    is_home = fm[1] == team_name
                    home_goals = fm[3]
                    away_goals = fm[4]
                    goals_for = home_goals if is_home else away_goals
                    goals_against = away_goals if is_home else home_goals
                    if goals_for is not None and goals_against is not None:
                        if goals_for > goals_against:
                            f_status = "W"
                        elif goals_for == goals_against:
                            f_status = "D"
                        else:
                            f_status = "L"
                    else:
                        f_status = None
                    form[side_name].append({
                        "date": fm[0].isoformat() if hasattr(fm[0], "isoformat") else str(fm[0]),
                        "opponent": fm[2] if is_home else fm[1],
                        "is_home": is_home,
                        "goals_for": goals_for,
                        "goals_against": goals_against,
                        "status": f_status,
                        "league": fm[5],
                    })

            # 7. Standings — latest snapshot for the team's competition season
            standings = []
            if home_team_id:
                cur.execute("""
                    SELECT DISTINCT ON (sss.team_id)
                           sss.rank, COALESCE(t.team_name_cn, t.team_name_en),
                           sss.played, sss.won, sss.drawn, sss.lost,
                           sss.goals_for, sss.goals_against, sss.goal_difference,
                           sss.points, sss.round_no
                    FROM season_standings_snapshots sss
                    JOIN teams t ON t.id = sss.team_id
                    WHERE sss.competition_season_id = (
                        SELECT sss2.competition_season_id
                        FROM season_standings_snapshots sss2
                        WHERE sss2.team_id = %s
                        ORDER BY sss2.snapshot_time DESC LIMIT 1
                    )
                    ORDER BY sss.team_id, sss.snapshot_time DESC
                """, (home_team_id,))
                for st in cur.fetchall():
                    standings.append({
                        "rank": st[0],
                        "team_name": st[1],
                        "played": st[2], "won": st[3], "drawn": st[4], "lost": st[5],
                        "goals_for": st[6], "goals_against": st[7],
                        "goal_diff": st[8], "points": st[9],
                        "round": st[10],
                    })
                # Sort by rank
                standings.sort(key=lambda s: s["rank"] or 999)

            # 8. Injuries
            injuries = []
            for tid in filter(None, [home_team_id, away_team_id]):
                cur.execute("""
                    SELECT pas.team_id, pas.availability_status,
                           pas.injury_type, pas.injury_body_part,
                           pas.expected_return_date, pas.absence_impact_score,
                           p.player_name_cn, p.player_name_en, p.primary_position
                    FROM player_availability_snapshots pas
                    LEFT JOIN players p ON p.id = pas.player_id
                    WHERE pas.team_id = %s
                      AND pas.availability_status IN ('injured', 'suspended', 'doubtful')
                    ORDER BY pas.absence_impact_score DESC NULLS LAST
                    LIMIT 20
                """, (tid,))
                for ij in cur.fetchall():
                    injuries.append({
                        "team_id": ij[0],
                        "status": ij[1],
                        "injury_type": ij[2],
                        "body_part": ij[3],
                        "expected_return": str(ij[4]) if ij[4] else None,
                        "impact_score": float(ij[5]) if ij[5] else None,
                        "player_name_cn": ij[6],
                        "player_name_en": ij[7],
                        "position": ij[8],
                    })

    return {
        "match": match_data,
        "scores": scores,
        "teams": teams_data,
        "predictions": predictions,
        "lineups": lineups,
        "feature_snapshot": feature_snapshot,
        "h2h": h2h,
        "form": form,
        "standings": standings,
        "injuries": injuries,
    }


@router.get("/api/events/all/matches")
def list_all_event_matches():
    """List all matches across all leagues (仅体彩官网数据)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.id, m.home_team_name, m.away_team_name, m.kickoff_time,
                       m.match_status, m.league_name,
                       COALESCE(m.raw_json->>'matchNumStr', m.official_match_code::text) AS match_num_str,
                       COALESCE(r.full_home_goals, (m.raw_json->>'hscore')::int) AS full_home_goals,
                       COALESCE(r.full_away_goals, (m.raw_json->>'gscore')::int) AS full_away_goals
                FROM official_matches m
                LEFT JOIN official_results r ON r.match_id = m.id
                WHERE m.raw_json->>'source' IS DISTINCT FROM '500.com'
                ORDER BY m.kickoff_time DESC
            """)
            rows = cur.fetchall()
    return {
        "matches": [
            {
                "match_id": r[0],
                "home_team_name": r[1],
                "away_team_name": r[2],
                "kickoff_time": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
                "match_status": r[4],
                "league_name": r[5],
                "match_num_str": r[6],
                "ft_home_goals": r[7] if len(r) > 7 else None,
                "ft_away_goals": r[8] if len(r) > 8 else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }
