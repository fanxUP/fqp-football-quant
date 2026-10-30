"""Legacy JC admission windows, separate from canonical season membership.

All retained windows apply independently. New current-season observations add
windows; they never revoke old ones or authorize deleting historical facts.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from psycopg2.extras import Json

type SeasonWindows = dict[str, list[tuple[date | str, date | str]]]


def load_retained_season_windows(conn: Any) -> SeasonWindows:
    windows: SeasonWindows = {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT league_name, season_start_date, season_end_date
               FROM official_event_season_retention
               ORDER BY league_name, season_start_date, season_end_date"""
        )
        for league, start, end in cur.fetchall():
            windows.setdefault(str(league), []).append((start, end))
    return windows


def allows_business_date(windows: SeasonWindows, league: str, day: date) -> bool:
    """Empty configuration permits bootstrap; configured gaps stay excluded."""
    return not windows or any(
        date.fromisoformat(str(start)) <= day <= date.fromisoformat(str(end))
        for start, end in windows.get(league, [])
    )


def retain_season_windows(conn: Any, windows: list[dict[str, Any]]) -> None:
    """Validate a complete batch and retain it without committing or deleting.

    Used by the current-season job and future verified historical scope import.
    Boundary changes retain both observations instead of taking a min/max union
    or silently shrinking an older admission. The caller owns the transaction.
    """
    if not windows:
        raise ValueError("no season windows supplied")
    normalized = []
    for window in windows:
        for field in (
            "league_name",
            "season_name",
            "boundary_source",
            "source_url",
            "selection_reason",
        ):
            if not isinstance(window.get(field), str) or not window[field].strip():
                raise ValueError(f"missing season window {field}")
        start = date.fromisoformat(str(window["start_date"]))
        end = date.fromisoformat(str(window["end_date"]))
        as_of = date.fromisoformat(str(window["as_of_date"]))
        if start > end:
            raise ValueError("season window starts after its end")
        refs = window["official_league_refs"]
        if not isinstance(refs, list):
            raise ValueError("official_league_refs must be a list")
        raw = json.loads(json.dumps(window, default=str))
        normalized.append(
            (
                window["league_name"],
                window["season_name"],
                start,
                end,
                window["selection_reason"],
                window["boundary_source"],
                Json(refs),
                window["source_url"],
                as_of,
                Json(raw),
            )
        )
    with conn.cursor() as cur:
        for params in normalized:
            cur.execute(
                """INSERT INTO official_event_season_retention (
                    league_name,season_name,season_start_date,season_end_date,
                    selection_reason,boundary_source,official_league_refs,
                    source_url,as_of_date,raw_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (league_name,season_name,season_start_date,season_end_date)
                DO UPDATE SET selection_reason=EXCLUDED.selection_reason,
                    boundary_source=EXCLUDED.boundary_source,
                    official_league_refs=EXCLUDED.official_league_refs,
                    source_url=EXCLUDED.source_url,as_of_date=EXCLUDED.as_of_date,
                    raw_json=EXCLUDED.raw_json,updated_at=now()
                WHERE EXCLUDED.as_of_date >= official_event_season_retention.as_of_date""",
                params,
            )
