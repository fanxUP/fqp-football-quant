"""Metadata-only audit storage for explicit model calls."""

from __future__ import annotations

from typing import Any


def record_model_invocation(
    conn: Any,
    *,
    agent_code: str,
    provider_code: str | None,
    model: str | None,
    status: str,
    prompt_length: int,
    response_length: int,
    duration_ms: int,
    error_code: str | None = None,
) -> None:
    """Persist call metadata only; request and response bodies never enter the database."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO llm_invocation_audits
                 (agent_code, provider_code, model, status, prompt_length, response_length, duration_ms, error_code)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (agent_code, provider_code, model, status, prompt_length, response_length, duration_ms, error_code),
        )
    conn.commit()


def list_model_invocations(conn: Any, limit: int = 30) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 50))
    with conn.cursor() as cur:
        cur.execute(
            """SELECT agent_code, provider_code, model, status, prompt_length, response_length,
                      duration_ms, error_code, created_at
               FROM llm_invocation_audits
               ORDER BY created_at DESC, id DESC
               LIMIT %s""",
            (safe_limit,),
        )
        rows = cur.fetchall()
    return [
        {
            "agentCode": row[0],
            "providerCode": row[1],
            "model": row[2],
            "status": row[3],
            "promptLength": row[4],
            "responseLength": row[5],
            "durationMs": row[6],
            "errorCode": row[7],
            "createdAt": row[8].isoformat() if row[8] else None,
        }
        for row in rows
    ]
