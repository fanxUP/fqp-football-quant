"""Read models for cold-result API and report consumers."""

from __future__ import annotations

from typing import Any

from psycopg2.extras import RealDictCursor


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def list_upset_reports(conn: Any, limit: int = 12) -> list[dict[str, Any]]:
    """Return current report artifacts without exposing local filesystem contents."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, report_type, period_start, period_end, report_version,
                   metrics_json, report_markdown, report_html,
                   (report_pdf_path IS NOT NULL) AS pdf_available,
                   validation_status, generated_at
            FROM upset_report_metrics
            ORDER BY period_end DESC, generated_at DESC, id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return _dict_rows(cur)


def list_upset_leagues(
    conn: Any,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Return league navigation options for the selected date range."""
    clauses = ["1 = 1"]
    params: dict[str, Any] = {}
    if start_date:
        clauses.append("event.business_date >= %(start_date)s")
        params["start_date"] = start_date
    if end_date:
        clauses.append("event.business_date <= %(end_date)s")
        params["end_date"] = end_date

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT match.league_name, COUNT(*) AS upset_count
            FROM upset_events event
            JOIN official_matches match ON match.id = event.match_id
            WHERE {" AND ".join(clauses)}
            GROUP BY match.league_name
            ORDER BY COUNT(*) DESC, match.league_name
            """,
            params,
        )
        rows = _dict_rows(cur)
    return [
        {"league_name": str(row["league_name"]), "upset_count": int(row["upset_count"])}
        for row in rows
    ]


def list_upsets(
    conn: Any,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    league_name: str | None = None,
    level: str | None = None,
    play_type: str | None = None,
    user_involved: bool | None = None,
    agent_involved: bool | None = None,
    review_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return filtered event cards and a total count in one database round trip."""
    clauses = ["1 = 1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    filters = {
        "event.business_date >= %(start_date)s": ("start_date", start_date),
        "event.business_date <= %(end_date)s": ("end_date", end_date),
        "match.league_name = %(league_name)s": ("league_name", league_name),
        "event.upset_level = %(level)s": ("level", level),
        "event.primary_play_type = %(play_type)s": ("play_type", play_type),
        "event.user_bet_involved = %(user_involved)s": ("user_involved", user_involved),
        "event.agent_bet_involved = %(agent_involved)s": (
            "agent_involved",
            agent_involved,
        ),
        "COALESCE(review.validation_status, 'waiting_data') = %(review_status)s": (
            "review_status",
            review_status,
        ),
    }
    for clause, (name, value) in filters.items():
        if value is not None:
            clauses.append(clause)
            params[name] = value

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT event.id, event.business_date, event.primary_play_type,
                   event.primary_upset_type, event.actual_outcome,
                   event.market_favourite_outcome,
                   event.market_favourite_probability,
                   event.actual_outcome_probability, event.surprise_bits,
                   event.upset_level, event.favourite_failed, event.model_warned,
                   event.user_bet_involved, event.agent_bet_involved,
                   event.detection_status, event.detected_at,
                   match.official_match_code, match.league_name,
                   match.home_team_name, match.away_team_name, match.kickoff_time,
                   CONCAT(result.full_home_goals, ':', result.full_away_goals) AS full_score,
                   COALESCE(review.validation_status, 'waiting_data') AS review_status,
                   review.data_completeness, review.confidence,
                   COUNT(*) OVER() AS total_count
            FROM upset_events event
            JOIN official_matches match ON match.id = event.match_id
            JOIN official_results result ON result.id = event.official_result_id
            LEFT JOIN LATERAL (
                SELECT validation_status, data_completeness, confidence
                FROM upset_reviews
                WHERE upset_event_id = event.id
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            ) review ON true
            WHERE {" AND ".join(clauses)}
            ORDER BY event.business_date DESC, event.surprise_bits DESC, event.id DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        rows = _dict_rows(cur)
    total = int(rows[0].pop("total_count")) if rows else 0
    for row in rows[1:]:
        row.pop("total_count", None)
    return rows, total


def get_upset_summary(
    conn: Any,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Aggregate market incidence and participation counts for one period."""
    clauses = ["1 = 1"]
    match_clauses = ["result.result_status IN ('final', 'confirmed')"]
    params: dict[str, Any] = {}
    if start_date:
        clauses.append("event.business_date >= %(start_date)s")
        match_clauses.append("match.business_date >= %(start_date)s")
        params["start_date"] = start_date
    if end_date:
        clauses.append("event.business_date <= %(end_date)s")
        match_clauses.append("match.business_date <= %(end_date)s")
        params["end_date"] = end_date

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS upset_count,
                   COUNT(*) FILTER (WHERE event.upset_level IN ('S', 'A')) AS severe_count,
                   COUNT(*) FILTER (WHERE event.upset_level = 'S') AS extreme_count,
                   COUNT(*) FILTER (WHERE event.favourite_failed) AS favourite_failed_count,
                   COUNT(*) FILTER (WHERE event.model_warned) AS model_warned_count,
                   COUNT(*) FILTER (WHERE event.user_bet_involved) AS user_involved_count,
                   COUNT(*) FILTER (WHERE event.agent_bet_involved) AS agent_involved_count
            FROM upset_events event
            WHERE {" AND ".join(clauses)}
            """,
            params,
        )
        totals = dict(cur.fetchone())
        cur.execute(
            f"""
            SELECT COUNT(*) AS settled_match_count
            FROM official_matches match
            JOIN official_results result ON result.match_id = match.id
            WHERE {" AND ".join(match_clauses)}
            """,
            params,
        )
        settled_match_count = int(cur.fetchone()["settled_match_count"] or 0)
        cur.execute(
            f"""
            SELECT COALESCE(event.upset_level, '热门未打出') AS key, COUNT(*) AS count
            FROM upset_events event
            WHERE {" AND ".join(clauses)}
            GROUP BY COALESCE(event.upset_level, '热门未打出')
            """,
            params,
        )
        level_counts = {str(row["key"]): int(row["count"]) for row in cur.fetchall()}
        cur.execute(
            f"""
            SELECT event.primary_play_type AS key, COUNT(*) AS count
            FROM upset_events event
            WHERE {" AND ".join(clauses)}
            GROUP BY event.primary_play_type
            """,
            params,
        )
        play_counts = {str(row["key"]): int(row["count"]) for row in cur.fetchall()}

    upset_count = int(totals["upset_count"] or 0)
    return {
        **{key: int(value or 0) for key, value in totals.items()},
        "settled_match_count": settled_match_count,
        "upset_rate": upset_count / settled_match_count if settled_match_count else 0.0,
        "level_counts": level_counts,
        "play_counts": play_counts,
    }


def _event_tickets(conn: Any, event_id: int, source: str) -> list[dict[str, Any]]:
    if source == "real":
        query = """
            SELECT DISTINCT ticket.id AS ticket_id, ticket.ticket_no,
                   ticket.total_amount AS stake_amount,
                   settlement.prize_amount, settlement.profit_loss,
                   settlement.roi, ticket.settlement_status
            FROM upset_events event
            JOIN real_ticket_items item ON item.match_id = event.match_id
            JOIN real_tickets ticket ON ticket.id = item.real_ticket_id
            LEFT JOIN ticket_settlements settlement
              ON settlement.ticket_source = 'real' AND settlement.ticket_id = ticket.id
            WHERE event.id = %s AND ticket.confirm_status = 'confirmed'
            ORDER BY ticket.id DESC
        """
    else:
        query = """
            SELECT DISTINCT ticket.id AS ticket_id, NULL::text AS ticket_no,
                   ticket.suggested_stake AS stake_amount,
                   settlement.prize_amount, settlement.profit_loss,
                   settlement.roi, ticket.ticket_status AS settlement_status
            FROM upset_events event
            JOIN simulation_ticket_items item ON item.match_id = event.match_id
            JOIN simulation_tickets ticket ON ticket.id = item.ticket_id
            LEFT JOIN ticket_settlements settlement
              ON settlement.ticket_source = 'simulation' AND settlement.ticket_id = ticket.id
            WHERE event.id = %s
              AND ticket.ticket_status IN ('generated', 'activated', 'settled')
            ORDER BY ticket.id DESC
        """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (event_id,))
        return _dict_rows(cur)


def get_upset_detail(conn: Any, event_id: int) -> dict[str, Any] | None:
    """Return one traceable event with every linked research surface."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT event.*, rule.rule_key,
                   match.official_match_code, match.league_name,
                   match.home_team_name, match.away_team_name,
                   match.kickoff_time, match.business_date,
                   result.full_home_goals, result.full_away_goals,
                   result.half_home_goals, result.half_away_goals
            FROM upset_events event
            JOIN upset_rule_versions rule ON rule.id = event.detect_rule_version_id
            JOIN official_matches match ON match.id = event.match_id
            JOIN official_results result ON result.id = event.official_result_id
            WHERE event.id = %s
            """,
            (event_id,),
        )
        event = cur.fetchone()
        if not event:
            return None
        cur.execute(
            """
            SELECT * FROM upset_market_signals
            WHERE upset_event_id = %s
            ORDER BY actual_outcome_probability, play_type, handicap NULLS LAST
            """,
            (event_id,),
        )
        signals = _dict_rows(cur)
        cur.execute(
            """
            SELECT * FROM upset_factor_evidence
            WHERE upset_event_id = %s
            ORDER BY evidence_phase, available_at, id
            """,
            (event_id,),
        )
        evidence = _dict_rows(cur)
        cur.execute(
            """
            SELECT * FROM upset_reviews
            WHERE upset_event_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (event_id,),
        )
        review_row = cur.fetchone()

    return {
        "event": dict(event),
        "market_signals": signals,
        "evidence": evidence,
        "review": dict(review_row) if review_row else None,
        "user_tickets": _event_tickets(conn, event_id, "real"),
        "agent_tickets": _event_tickets(conn, event_id, "simulation"),
    }
