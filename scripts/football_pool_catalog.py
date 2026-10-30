"""Read-only current official pool memberships; no prediction/admission changes.

Filters select whole issues, never trim their official match orders. Legacy
TIMESTAMP kickoffs are Beijing wall time. Season membership is not inferred
from dates or from the old single-season retention windows.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from scripts.football_fixture_identity import TRADITIONAL_MATCH_COUNTS
from scripts.pool_issue_state import pool_time, sale_window


def _iso(value: Any) -> str | None:
    instant = pool_time(value)
    return instant.isoformat() if instant else None


def _summary(row: tuple) -> dict:
    (
        iid,
        number,
        game,
        total,
        source_game,
        raw,
        stored,
        linked,
        pending,
        conflict,
        unique,
        orders,
        first,
        last,
    ) = row
    expected = TRADITIONAL_MATCH_COUNTS[game]
    return {
        "id": iid,
        "issue_no": number,
        "game_type": game,
        "total_matches": total,
        "expected_matches": expected,
        "stored_matches": stored,
        "linked_matches": linked,
        "pending_matches": pending,
        "conflict_matches": conflict,
        "unique_fixtures": unique,
        "source_verified": source_game == game,
        "catalogue_complete": source_game == game
        and total == expected
        and orders == list(range(1, expected + 1)),
        "first_kickoff": _iso(first),
        "last_kickoff": _iso(last),
        **sale_window(raw or {}),
    }


# Aggregate only the bounded page, not every issue or a multi-million-row fact
# table. COUNT(DISTINCT fixture_id) is per issue, not across the page's games.
_SUMMARY_SQL = """
SELECT i.id,i.issue_no,i.game_type,i.total_matches,i.source_game_type,i.raw_json,
       s.stored,s.linked,s.pending,s.conflict,s.unique_fixtures,s.orders,s.first,s.last
FROM page i CROSS JOIN LATERAL (
    SELECT count(*) AS stored,
           count(*) FILTER (WHERE identity_status='linked') AS linked,
           count(*) FILTER (WHERE identity_status='pending') AS pending,
           count(*) FILTER (WHERE identity_status='conflict') AS conflict,
           count(DISTINCT fixture_id) AS unique_fixtures,
           array_agg(match_order ORDER BY match_order) AS orders,
           min(kickoff_time) AS first,max(kickoff_time) AS last
    FROM football_pool_fixture_catalog WHERE issue_id=i.id
) s ORDER BY i.issue_no DESC,i.id DESC
"""


def read_pool_catalog(
    conn: Any,
    *,
    game_type: str | None = None,
    issue_no: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Caller owns repeatable-read/readonly transaction and input validation."""
    clauses = ["i.game_type IN ('t14c','r9','bqc6','jq4')"]
    params: list[Any] = []
    if game_type:
        clauses.append("i.game_type=%s")
        params.append(game_type)
    if issue_no:
        clauses.append("i.issue_no=%s")
        params.append(issue_no)
    date_clauses = []
    if date_from:
        date_clauses.append("m.kickoff_time >= %s")
        params.append(datetime.combine(date_from, time.min))
    if date_to:
        date_clauses.append("m.kickoff_time < %s")
        params.append(datetime.combine(date_to + timedelta(days=1), time.min))
    if date_clauses:
        clauses.append(
            "EXISTS (SELECT 1 FROM football_pool_issue_matches m WHERE m.issue_id=i.id AND "
            + " AND ".join(date_clauses)
            + ")"
        )
    where = " AND ".join(clauses)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM football_pool_issues i WHERE " + where, params)
        total = cur.fetchone()[0]
        cur.execute(
            "WITH page AS (SELECT i.* FROM football_pool_issues i WHERE "
            + where
            + " ORDER BY i.issue_no DESC,i.id DESC LIMIT %s OFFSET %s) "
            + _SUMMARY_SQL,
            [*params, limit, offset],
        )
        issues = [_summary(row) for row in cur.fetchall()]
    return {"issues": issues, "total": total, "limit": limit, "offset": offset}


def read_pool_catalog_issue(conn: Any, issue_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "WITH page AS (SELECT * FROM football_pool_issues WHERE id=%s "
            "AND game_type IN ('t14c','r9','bqc6','jq4')) " + _SUMMARY_SQL,
            (issue_id,),
        )
        header = cur.fetchone()
        if header is None:
            return None
        cur.execute(
            """SELECT match_order,fixture_id,official_match_id,identity_status,
                      identity_evidence->>'reason',league_name,home_team_name,away_team_name,kickoff_time
               FROM football_pool_fixture_catalog WHERE issue_id=%s ORDER BY match_order""",
            (issue_id,),
        )
        fixtures = [
            {
                "match_order": order,
                "fixture_id": fid,
                "official_match_id": official_id,
                "identity_status": status,
                "identity_reason": reason,
                "league": league or "",
                "home_team": home or "",
                "away_team": away or "",
                "kickoff": _iso(kickoff),
            }
            for order, fid, official_id, status, reason, league, home, away, kickoff in cur.fetchall()
        ]
    return {"issue": _summary(header), "fixtures": fixtures, "season_status": "pending"}
