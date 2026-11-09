"""Read-only official pool memberships and their recorded market references.

Filters select whole issues, never trim their official match orders. Legacy
TIMESTAMP kickoffs are Beijing wall time. Season membership is not inferred
from dates or from the old single-season retention windows.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from scripts.football_fixture_identity import TRADITIONAL_MATCH_COUNTS
from scripts.play_type_registry import TRADITIONAL_SCHEDULE_GAME_CODES
from scripts.pool_issue_state import pool_time, sale_window


def _iso(value: Any) -> str | None:
    instant = pool_time(value)
    return instant.isoformat() if instant else None


def _day_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _summary(row: tuple) -> dict:
    (
        iid,
        number,
        game,
        total,
        source_game,
        source_game_no,
        source_game_no_source,
        raw,
        stored,
        linked,
        pending,
        conflict,
        unique,
        orders,
        first_date,
        last_date,
        first,
        last,
    ) = row
    expected = TRADITIONAL_MATCH_COUNTS[game]
    if (
        source_game == game
        and isinstance(raw, dict)
        and raw.get("_source") == "sporttery_live_schedule"
    ):
        code = TRADITIONAL_SCHEDULE_GAME_CODES[game]
        if str(raw.get("lotteryGameNum")) == str(code):
            source_game_no, source_game_no_source = code, "sporttery_live_schedule"
    return {
        "id": iid,
        "issue_no": number,
        "game_type": game,
        "source_game_no": source_game_no,
        "source_game_no_source": source_game_no_source,
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
        "first_kickoff_date": _day_iso(first_date),
        "last_kickoff_date": _day_iso(last_date),
        "first_kickoff": _iso(first),
        "last_kickoff": _iso(last),
        **sale_window(raw or {}),
    }


# Aggregate only the bounded page, not every issue or a multi-million-row fact
# table. COUNT(DISTINCT fixture_id) is per issue, not across the page's games.
_SUMMARY_SQL = """
SELECT i.id,i.issue_no,i.game_type,i.total_matches,i.source_game_type,
       i.source_game_no,i.source_game_no_source,i.raw_json,
       s.stored,s.linked,s.pending,s.conflict,s.unique_fixtures,s.orders,
       s.first_date,s.last_date,s.first,s.last
FROM page i CROSS JOIN LATERAL (
    SELECT count(*) AS stored,
           count(*) FILTER (WHERE identity_status='linked') AS linked,
           count(*) FILTER (WHERE identity_status='pending') AS pending,
           count(*) FILTER (WHERE identity_status='conflict') AS conflict,
           count(DISTINCT fixture_id) AS unique_fixtures,
           array_agg(match_order ORDER BY match_order) AS orders,
           min(COALESCE(kickoff_date,kickoff_time::date)) AS first_date,
           max(COALESCE(kickoff_date,kickoff_time::date)) AS last_date,
           min(kickoff_time) FILTER (WHERE kickoff_time_precision IN ('minute','second')) AS first,
           max(kickoff_time) FILTER (WHERE kickoff_time_precision IN ('minute','second')) AS last
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
        date_clauses.append("COALESCE(m.kickoff_date,m.kickoff_time::date) >= %s")
        params.append(date_from)
    if date_to:
        date_clauses.append("COALESCE(m.kickoff_date,m.kickoff_time::date) <= %s")
        params.append(date_to)
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
            """SELECT c.match_order,c.fixture_id,c.official_match_id,c.identity_status,
                      c.identity_evidence->>'reason',c.league_name,c.home_team_name,c.away_team_name,
                      c.kickoff_time,c.kickoff_date,c.kickoff_time_precision,
                      source_full_home_goals,source_full_away_goals,
                      source_half_home_goals,source_half_away_goals,
                      source_product_result_code,source_result_semantics_key,
                      source_result_source,r.reference,r.quote_at,r.observed_at,
                      r.published_at,r.target_at
               FROM football_pool_fixture_catalog c
               LEFT JOIN football_fixture_identity_aliases a ON a.canonical_fixture_id=c.fixture_id
               LEFT JOIN LATERAL (
                 SELECT reference,quote_at,observed_at,published_at,target_at
                 FROM football_fixture_market_references
                 WHERE fixture_id IN (c.fixture_id,a.alias_fixture_id)
                   AND kickoff_at=c.kickoff_time AT TIME ZONE 'Asia/Shanghai'
                   AND published_at IS NOT NULL
                 ORDER BY target_at DESC,published_at DESC LIMIT 1
               ) r ON TRUE
               WHERE c.issue_id=%s ORDER BY c.match_order""",
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
                "kickoff": _iso(kickoff) if precision in {"minute", "second"} else None,
                "kickoff_date": _day_iso(kickoff_date) or _day_iso(kickoff),
                "kickoff_time_precision": precision,
                "source_full_home_goals": full_home,
                "source_full_away_goals": full_away,
                "source_half_home_goals": half_home,
                "source_half_away_goals": half_away,
                "source_product_result_code": result_code,
                "source_result_semantics_key": result_semantics,
                "source_result_source": result_source,
                "market_reference": {
                    **reference,
                    "quote_at": _iso(quoted),
                    "observed_at": _iso(observed),
                    "published_at": _iso(published),
                    "target_at": _iso(target),
                }
                if reference is not None
                else None,
            }
            for (
                order,
                fid,
                official_id,
                status,
                reason,
                league,
                home,
                away,
                kickoff,
                kickoff_date,
                precision,
                full_home,
                full_away,
                half_home,
                half_away,
                result_code,
                result_semantics,
                result_source,
                reference,
                quoted,
                observed,
                published,
                target,
            ) in cur.fetchall()
        ]
    return {"issue": _summary(header), "fixtures": fixtures, "season_status": "pending"}
