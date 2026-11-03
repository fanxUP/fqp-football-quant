"""Append source-backed actual match results without changing pool settlement."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from psycopg2.extras import Json

MATCH_STATUSES = {
    "completed",
    "shortened",
    "abandoned",
    "postponed",
    "cancelled",
    "awarded",
    "unknown",
}
SCORE_BASES = {"on_field", "awarded", "unknown"}
SCORE_PERIODS = {"regulation", "extra_time", "penalties", "unknown"}
KICKOFF_PRECISION = {"second", "minute", "date_only", "unknown"}
EVIDENCE_CONTRACT = "football-match-result-fact/v1"

_FIELDS = {
    "fixture_id",
    "source_name",
    "id_system",
    "source_match_id",
    "actual_match_date",
    "actual_kickoff_at",
    "kickoff_time_precision",
    "match_status",
    "score_basis",
    "score_period",
    "half_home_goals",
    "half_away_goals",
    "full_home_goals",
    "full_away_goals",
    "source_published_at",
    "source_payload",
    "evidence",
}
_SCORE_FIELDS = (
    "half_home_goals",
    "half_away_goals",
    "full_home_goals",
    "full_away_goals",
)
_TIMESTAMP_FIELDS = ("actual_kickoff_at", "source_published_at")


def _as_date(value: Any, field: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise ValueError(f"{field} must be a date without a time")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date or null")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date or null") from exc


def _as_timestamp(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO timestamp or null") from exc
    else:
        raise ValueError(f"{field} must be an ISO timestamp or null")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone offset")
    return parsed


def validate_result_fact(record: dict[str, Any]) -> dict[str, Any]:
    """Validate a complete, source-backed result observation without database access."""
    if not isinstance(record, dict) or set(record) != _FIELDS:
        raise ValueError("result fact fields must exactly match the v1 contract")

    fixture_id = record["fixture_id"]
    if type(fixture_id) is not int or fixture_id <= 0:
        raise ValueError("fixture_id must be a positive integer")

    normalized: dict[str, Any] = dict(record)
    for field in ("source_name", "id_system", "source_match_id"):
        value = record[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        normalized[field] = value.strip()

    normalized["actual_match_date"] = _as_date(record["actual_match_date"], "actual_match_date")
    for field in _TIMESTAMP_FIELDS:
        normalized[field] = _as_timestamp(record[field], field)

    precision = record["kickoff_time_precision"]
    if precision not in KICKOFF_PRECISION:
        raise ValueError("kickoff_time_precision is not supported")
    normalized["kickoff_time_precision"] = precision
    if precision in {"second", "minute"} and normalized["actual_kickoff_at"] is None:
        raise ValueError("minute/second kickoff precision requires actual_kickoff_at")
    if precision == "date_only" and normalized["actual_match_date"] is None:
        raise ValueError("date-only kickoff precision requires actual_match_date")
    if precision in {"date_only", "unknown"} and normalized["actual_kickoff_at"] is not None:
        raise ValueError("date-only/unknown kickoff precision cannot include actual_kickoff_at")
    if normalized["actual_kickoff_at"] is not None and normalized["actual_match_date"] is None:
        raise ValueError("actual_kickoff_at requires actual_match_date")

    for field, allowed in (
        ("match_status", MATCH_STATUSES),
        ("score_basis", SCORE_BASES),
        ("score_period", SCORE_PERIODS),
    ):
        value = record[field]
        if not isinstance(value, str) or value not in allowed:
            raise ValueError(f"{field} is not supported")
    if record["match_status"] == "completed" and record["score_basis"] == "awarded":
        raise ValueError("a completed match cannot use an awarded score basis")

    for field in _SCORE_FIELDS:
        value = record[field]
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{field} must be a non-negative integer or null")
    for first, second in (
        ("half_home_goals", "half_away_goals"),
        ("full_home_goals", "full_away_goals"),
    ):
        if (record[first] is None) != (record[second] is None):
            raise ValueError(f"{first} and {second} must be present together")

    for field in ("source_payload", "evidence"):
        if not isinstance(record[field], dict) or not record[field]:
            raise ValueError(f"{field} must be a non-empty object")
    evidence = record["evidence"]
    if evidence.get("contract") != EVIDENCE_CONTRACT:
        raise ValueError("evidence contract is not supported")
    identity = evidence.get("identity")
    if not isinstance(identity, dict) or identity != {
        "fixture_id": fixture_id,
        "source_name": normalized["source_name"],
        "id_system": normalized["id_system"],
        "source_match_id": normalized["source_match_id"],
    }:
        raise ValueError("evidence identity does not match the result fact")
    if not isinstance(evidence.get("source_reference"), dict) or not evidence["source_reference"]:
        raise ValueError("evidence.source_reference must identify its evidence")

    return normalized


def store_result_fact(conn: Any, record: dict[str, Any]) -> dict[str, Any]:
    """Append an observation idempotently; the caller owns commit/rollback."""
    fact = validate_result_fact(record)
    identity = (
        fact["source_name"],
        fact["id_system"],
        fact["source_match_id"],
        fact["fixture_id"],
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT fixture_id
            FROM football_fixture_source_links
            WHERE source_name=%s AND id_system=%s AND source_match_id=%s
            """,
            identity[:3],
        )
        link = cur.fetchone()
        if not link or link[0] != fact["fixture_id"]:
            raise ValueError("result fact source identity is not bound to fixture_id")

        cur.execute(
            """
            INSERT INTO football_fixture_result_facts (
                fixture_id,source_name,id_system,source_match_id,
                actual_match_date,actual_kickoff_at,kickoff_time_precision,
                match_status,score_basis,score_period,
                half_home_goals,half_away_goals,full_home_goals,full_away_goals,
                source_published_at,source_payload,evidence
            ) VALUES (
                %(fixture_id)s,%(source_name)s,%(id_system)s,%(source_match_id)s,
                %(actual_match_date)s,%(actual_kickoff_at)s,%(kickoff_time_precision)s,
                %(match_status)s,%(score_basis)s,%(score_period)s,
                %(half_home_goals)s,%(half_away_goals)s,%(full_home_goals)s,%(full_away_goals)s,
                %(source_published_at)s,%(source_payload)s,%(evidence)s
            )
            ON CONFLICT (source_name,id_system,source_match_id,source_payload_sha256)
            DO NOTHING
            RETURNING id,source_payload_sha256,evidence_sha256,model_eligible,true AS inserted
            """,
            {
                **fact,
                "source_payload": Json(fact["source_payload"]),
                "evidence": Json(fact["evidence"]),
            },
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                """
                SELECT id,source_payload_sha256,evidence_sha256,model_eligible,
                       evidence_sha256=encode(
                           sha256(jsonb_send(%(evidence)s::jsonb)),'hex'
                       ) AS evidence_matches,
                       fixture_id,actual_match_date,actual_kickoff_at,kickoff_time_precision,
                       match_status,score_basis,score_period,
                       half_home_goals,half_away_goals,full_home_goals,full_away_goals,
                       source_published_at,source_payload,evidence
                FROM football_fixture_result_facts
                WHERE source_name=%(source_name)s
                  AND id_system=%(id_system)s
                  AND source_match_id=%(source_match_id)s
                  AND source_payload_sha256=encode(
                      sha256(jsonb_send(%(source_payload)s::jsonb)),'hex'
                  )
                """,
                {
                    **fact,
                    "source_payload": Json(fact["source_payload"]),
                    "evidence": Json(fact["evidence"]),
                },
            )
            existing = cur.fetchone()
            if existing is None:
                raise RuntimeError("conflicting result fact was not visible after insert retry")
            expected_facts = (
                fact["fixture_id"],
                fact["actual_match_date"],
                fact["actual_kickoff_at"],
                fact["kickoff_time_precision"],
                fact["match_status"],
                fact["score_basis"],
                fact["score_period"],
                fact["half_home_goals"],
                fact["half_away_goals"],
                fact["full_home_goals"],
                fact["full_away_goals"],
                fact["source_published_at"],
                fact["source_payload"],
                fact["evidence"],
            )
            if not existing[4] or tuple(existing[5:]) != expected_facts:
                raise ValueError(
                    "same source payload has conflicting parsed result facts or evidence"
                )
            row = (*existing[:4], False)
    return {
        "id": row[0],
        "source_payload_sha256": row[1],
        "evidence_sha256": row[2],
        "model_eligible": row[3],
        "inserted": row[4],
    }
