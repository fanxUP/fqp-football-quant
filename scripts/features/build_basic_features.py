"""Basic match feature computation from available Stage 2 data.

Computes features that don't require external data sources:
  - Odds-implied probabilities (from official_odds_snapshots)
  - Rest days between matches
  - Team form from historical results
  - Data completeness scoring

All features are computed from data already in PostgreSQL (Stage 2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def compute_odds_implied_probabilities(
    snapshots: list[dict],
) -> dict[str, float | None]:
    """Convert latest SP odds to implied probabilities.

    Takes the most recent odds snapshot per play_type and applies
    basic normalization (removing overround).

    Returns:
        dict with keys: home_win_prob, draw_prob, away_win_prob,
                        home_win_prob_hhad, draw_prob_hhad, away_win_prob_hhad
    """
    result: dict[str, float | None] = {
        "home_win_prob": None,
        "draw_prob": None,
        "away_win_prob": None,
        "home_win_prob_hhad": None,
        "draw_prob_hhad": None,
        "away_win_prob_hhad": None,
    }

    # Group latest snapshot by play_type
    latest: dict[str, dict[str, float]] = {}
    for snap in snapshots:
        pt = snap.get("play_type", "")
        opt = snap.get("option_code", "")
        sp = snap.get("sp_value")
        if pt not in latest:
            latest[pt] = {}
        if opt and sp:
            latest[pt][opt] = float(sp)

    for play_type, odds in latest.items():
        if "h" not in odds or "d" not in odds or "a" not in odds:
            continue
        # Convert odds to raw probabilities (1/odds)
        raw_h = 1.0 / odds["h"]
        raw_d = 1.0 / odds["d"]
        raw_a = 1.0 / odds["a"]
        total = raw_h + raw_d + raw_a
        # Normalize (remove overround)
        suffix = "_hhad" if play_type == "rqspf" else ""
        result[f"home_win_prob{suffix}"] = round(raw_h / total, 4) if total > 0 else None
        result[f"draw_prob{suffix}"] = round(raw_d / total, 4) if total > 0 else None
        result[f"away_win_prob{suffix}"] = round(raw_a / total, 4) if total > 0 else None

    return result


def compute_rest_days(team_name: str, match_kickoff: str, conn: Any) -> int | None:
    """Compute rest days since the team's previous match.

    Queries official_matches for the given team's most recent kickoff
    before `match_kickoff`.

    Args:
        team_name: official team name (home_team_name or away_team_name)
        match_kickoff: ISO-format kickoff time of the current match
        conn: database connection

    Returns:
        Number of rest days, or None if no previous match found.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kickoff_time FROM official_matches
            WHERE (home_team_name = %(team)s OR away_team_name = %(team)s)
              AND kickoff_time < %(kickoff)s
            ORDER BY kickoff_time DESC LIMIT 1
            """,
            {"team": team_name, "kickoff": match_kickoff},
        )
        row = cur.fetchone()
    if not row or not row[0]:
        return None

    try:
        prev_kickoff = row[0]
        if isinstance(prev_kickoff, str):
            prev_kickoff = datetime.fromisoformat(prev_kickoff.replace("Z", "+00:00"))
        current = datetime.fromisoformat(match_kickoff.replace("Z", "+00:00"))
        delta = (current - prev_kickoff).days
        return delta
    except (ValueError, TypeError):
        return None


def compute_data_completeness(
    has_odds: bool = False,
    has_team_mapping: bool = False,
    has_team_profile: bool = False,
    has_lineup: bool = False,
    has_injury: bool = False,
    has_weather: bool = False,
    has_motivation: bool = False,
) -> dict[str, float]:
    """Compute data completeness and uncertainty scores.

    Weighted scoring based on which data components are available.
    Formula from docs/04: official(40%) + odds(25%) + third-party(20%) + mapping(15%)
    Simplified for Stage 3a: odds(40%) + team_mapping(35%) + team_profile(25%)
    """
    weights = {
        "has_odds": 0.40,
        "has_team_mapping": 0.35,
        "has_team_profile": 0.25,
    }
    score = 0.0
    if has_odds:
        score += weights["has_odds"] * 100
    if has_team_mapping:
        score += weights["has_team_mapping"] * 100
    if has_team_profile:
        score += weights["has_team_profile"] * 100

    completeness = round(score, 1)

    # Uncertainty: higher when data is missing
    missing_components = 0
    if not has_odds:
        missing_components += 1
    if not has_team_mapping:
        missing_components += 1
    if not has_team_profile:
        missing_components += 1

    uncertainty = round(missing_components * 25.0, 1)  # 0-75 range

    return {
        "data_completeness_score": completeness,
        "uncertainty_score": uncertainty,
    }


def compute_team_form(
    team_name: str, before_kickoff: str, last_n: int, conn: Any
) -> dict[str, Any]:
    """Compute recent form for a team from historical results.

    Queries official_matches + official_results to find the team's
    last N completed matches before `before_kickoff`.

    Returns:
        dict with wins, draws, losses, goals_for, goals_against, form_string
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                m.home_team_name, m.away_team_name,
                r.full_home_goals, r.full_away_goals,
                m.kickoff_time
            FROM official_matches m
            JOIN official_results r ON r.match_id = m.id
            WHERE (m.home_team_name = %(team)s OR m.away_team_name = %(team)s)
              AND m.kickoff_time < %(kickoff)s
              AND r.full_home_goals IS NOT NULL
            ORDER BY m.kickoff_time DESC
            LIMIT %(limit)s
            """,
            {"team": team_name, "kickoff": before_kickoff, "limit": last_n},
        )
        rows = cur.fetchall()

    wins, draws, losses = 0, 0, 0
    goals_for, goals_against = 0, 0
    form_chars: list[str] = []

    for home, _away, fh, fa, _ in rows:
        is_home = home == team_name
        gf = fh if is_home else fa
        ga = fa if is_home else fh
        goals_for += gf or 0
        goals_against += ga or 0

        if gf is not None and ga is not None:
            if gf > ga:
                wins += 1
                form_chars.append("W")
            elif gf == ga:
                draws += 1
                form_chars.append("D")
            else:
                losses += 1
                form_chars.append("L")
        else:
            form_chars.append("?")

    played = wins + draws + losses
    return {
        "matches_played": played,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "goal_diff": goals_for - goals_against,
        "points": wins * 3 + draws,
        "recent_form_5": "".join(form_chars[:5]),
    }
