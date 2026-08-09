"""Leakage-safe cold-result risk features for pre-match model snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg2.extras import RealDictCursor

MIN_GLOBAL_HISTORY = 20
PRIOR_SAMPLE_SIZE = 10
CONFIDENCE_TARGET_SAMPLE_SIZE = 30


def _smoothed_rate(upsets: int, matches: int, prior_rate: float) -> float:
    return (upsets + prior_rate * PRIOR_SAMPLE_SIZE) / (matches + PRIOR_SAMPLE_SIZE)


def build_upset_risk_features(metrics: dict[str, Any] | None) -> dict[str, float | int | None]:
    """Return risk features from historical settled matches only.

    The loader supplies rows strictly before a target match's kickoff.  Rates use
    a global empirical-Bayes prior, so a small league or team sample cannot
    dominate an otherwise stable risk estimate.
    """
    empty: dict[str, float | int | None] = {
        "upset_risk_score": None,
        "league_upset_rate": None,
        "home_team_upset_rate": None,
        "away_team_upset_rate": None,
        "upset_risk_confidence": None,
        "upset_risk_sample_size": 0,
    }
    if not metrics:
        return empty
    global_matches = int(metrics.get("global_match_count") or 0)
    global_upsets = int(metrics.get("global_upset_count") or 0)
    if global_matches < MIN_GLOBAL_HISTORY:
        return empty

    global_rate = global_upsets / global_matches
    league_matches = int(metrics.get("league_match_count") or 0)
    home_matches = int(metrics.get("home_match_count") or 0)
    away_matches = int(metrics.get("away_match_count") or 0)
    league_rate = _smoothed_rate(int(metrics.get("league_upset_count") or 0), league_matches, global_rate)
    home_rate = _smoothed_rate(int(metrics.get("home_upset_count") or 0), home_matches, global_rate)
    away_rate = _smoothed_rate(int(metrics.get("away_upset_count") or 0), away_matches, global_rate)
    confidence = sum(
        min(sample / CONFIDENCE_TARGET_SAMPLE_SIZE, 1.0)
        for sample in (league_matches, home_matches, away_matches)
    ) / 3
    return {
        "upset_risk_score": round(0.5 * league_rate + 0.25 * home_rate + 0.25 * away_rate, 6),
        "league_upset_rate": round(league_rate, 6),
        "home_team_upset_rate": round(home_rate, 6),
        "away_team_upset_rate": round(away_rate, 6),
        "upset_risk_confidence": round(confidence, 6),
        "upset_risk_sample_size": global_matches,
    }


def load_pre_kickoff_upset_risk(
    conn: Any,
    *,
    league_name: str,
    home_team_id: int | None,
    away_team_id: int | None,
    kickoff_time: datetime,
) -> dict[str, float | int | None]:
    """Load only settled historical outcomes that were known before kickoff."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH historical AS (
                SELECT match.kickoff_time, match.league_name,
                       home_alias.team_id AS home_team_id,
                       away_alias.team_id AS away_team_id,
                       (event.id IS NOT NULL) AS is_upset
                FROM official_matches match
                JOIN official_results result ON result.match_id = match.id
                LEFT JOIN upset_events event ON event.match_id = match.id
                LEFT JOIN team_aliases home_alias
                  ON home_alias.source_name = 'sporttery'
                 AND home_alias.alias_name = match.home_team_name
                LEFT JOIN team_aliases away_alias
                  ON away_alias.source_name = 'sporttery'
                 AND away_alias.alias_name = match.away_team_name
                WHERE result.result_status IN ('final', 'confirmed')
            )
            SELECT
                COUNT(*) FILTER (WHERE historical.kickoff_time < %(kickoff_time)s) AS global_match_count,
                COUNT(*) FILTER (WHERE historical.kickoff_time < %(kickoff_time)s AND is_upset) AS global_upset_count,
                COUNT(*) FILTER (WHERE historical.kickoff_time < %(kickoff_time)s AND league_name = %(league_name)s) AS league_match_count,
                COUNT(*) FILTER (WHERE historical.kickoff_time < %(kickoff_time)s AND league_name = %(league_name)s AND is_upset) AS league_upset_count,
                COUNT(*) FILTER (WHERE historical.kickoff_time < %(kickoff_time)s AND (%(home_team_id)s IN (home_team_id, away_team_id))) AS home_match_count,
                COUNT(*) FILTER (WHERE historical.kickoff_time < %(kickoff_time)s AND (%(home_team_id)s IN (home_team_id, away_team_id)) AND is_upset) AS home_upset_count,
                COUNT(*) FILTER (WHERE historical.kickoff_time < %(kickoff_time)s AND (%(away_team_id)s IN (home_team_id, away_team_id))) AS away_match_count,
                COUNT(*) FILTER (WHERE historical.kickoff_time < %(kickoff_time)s AND (%(away_team_id)s IN (home_team_id, away_team_id)) AND is_upset) AS away_upset_count
            FROM historical
            """,
            {
                "kickoff_time": kickoff_time,
                "league_name": league_name,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
            },
        )
        row = cur.fetchone()
    return build_upset_risk_features(dict(row) if row else None)
