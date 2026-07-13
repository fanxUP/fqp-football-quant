"""Build source-labelled standings from settled supplemental matches."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.feature_storage import store_season_standings_snapshot


def calculate(rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    table: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"played": 0, "won": 0, "drawn": 0, "lost": 0,
                 "goals_for": 0, "goals_against": 0, "points": 0}
    )
    for home_id, away_id, home_goals, away_goals in rows:
        if None in (home_id, away_id, home_goals, away_goals):
            continue
        home, away = table[home_id], table[away_id]
        home["played"] += 1
        away["played"] += 1
        home["goals_for"] += home_goals
        home["goals_against"] += away_goals
        away["goals_for"] += away_goals
        away["goals_against"] += home_goals
        if home_goals > away_goals:
            home["won"] += 1
            away["lost"] += 1
            home["points"] += 3
        elif home_goals < away_goals:
            away["won"] += 1
            home["lost"] += 1
            away["points"] += 3
        else:
            home["drawn"] += 1
            away["drawn"] += 1
            home["points"] += 1
            away["points"] += 1
    ordered = sorted(table.items(), key=lambda item: (
        -item[1]["points"],
        -(item[1]["goals_for"] - item[1]["goals_against"]),
        -item[1]["goals_for"],
        item[0],
    ))
    result = []
    for rank, (team_id, values) in enumerate(ordered, 1):
        result.append({"team_id": team_id, "rank": rank,
                       "goal_difference": values["goals_for"] - values["goals_against"], **values})
    return result


def run() -> dict[str, Any]:
    written = 0
    reports = []
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT competition_season_id, home_team_id, away_team_id,
                       full_home_goals, full_away_goals
                FROM supplemental_matches
                WHERE match_status IN ('Settled', 'Finished')
                  AND full_home_goals IS NOT NULL AND full_away_goals IS NOT NULL
                  AND competition_season_id IS NOT NULL
                """
            )
            grouped: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
            for season_id, home_id, away_id, home_goals, away_goals in cur.fetchall():
                grouped[season_id].append((home_id, away_id, home_goals, away_goals))
            snapshot_time = datetime.now().isoformat(timespec="seconds")
            for season_id, rows in grouped.items():
                standings = calculate(rows)
                for item in standings:
                    stored = {
                        **item,
                        "competition_season_id": season_id,
                        "snapshot_time": snapshot_time,
                        "source_name": "500com_derived",
                        "source_confidence": 0.75,
                        "raw_json": {
                            "source": "500.com",
                            "derivation": "settled_supplemental_matches",
                            "settled_match_count": len(rows),
                        },
                    }
                    store_season_standings_snapshot(conn, stored)
                    written += 1
                reports.append({"competition_season_id": season_id,
                                "settled_matches": len(rows),
                                "teams": len(standings)})
        conn.commit()
    return {"status": "ok", "written": written, "reports": reports,
            "snapshot_time": snapshot_time}


if __name__ == "__main__":
    print(run())
