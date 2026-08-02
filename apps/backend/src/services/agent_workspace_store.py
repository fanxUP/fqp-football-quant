"""Persistence for explicitly created, human-reviewed agent workspace tasks."""

from __future__ import annotations

from typing import Any


class AgentWorkspaceError(ValueError):
    """Raised when a workspace task cannot be safely read or changed."""


def _serialize(row: tuple[Any, ...], *, include_content: bool = True) -> dict[str, Any]:
    task = {
        "id": row[0], "title": row[1], "agentCode": row[2], "providerCode": row[3],
        "model": row[4], "reviewNote": row[5], "reviewedAt": row[6].isoformat() if row[6] else None,
        "createdAt": row[7].isoformat() if row[7] else None,
    }
    if include_content:
        task.update({"prompt": row[8], "response": row[9]})
    return task


def create_workspace_task(
    conn: Any, *, title: str, agent_code: str, provider_code: str, model: str, prompt: str, response: str
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO agent_workspace_tasks
                   (title, agent_code, provider_code, model, prompt, response)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, title, agent_code, provider_code, model, review_note, reviewed_at, created_at, prompt, response""",
            (title, agent_code, provider_code, model, prompt, response),
        )
        row = cur.fetchone()
    conn.commit()
    return _serialize(row)


def list_workspace_tasks(conn: Any, limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 50))
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, title, agent_code, provider_code, model, review_note, reviewed_at, created_at, prompt, response
               FROM agent_workspace_tasks ORDER BY created_at DESC, id DESC LIMIT %s""",
            (safe_limit,),
        )
        rows = cur.fetchall()
    return [_serialize(row) for row in rows]


def list_workspace_task_page(
    conn: Any, *, limit: int = 20, offset: int = 0, review_status: str = "all", query: str = ""
) -> tuple[list[dict[str, Any]], int]:
    """Return a bounded archive page and its matching total.

    The status clause is selected from a fixed allowlist; user values are never
    interpolated into SQL.  The router validates the status before this call.
    """
    safe_limit = max(1, min(limit, 50))
    safe_offset = max(0, offset)
    clauses = {"pending": "reviewed_at IS NULL", "reviewed": "reviewed_at IS NOT NULL"}
    conditions = [clauses[review_status]] if review_status in clauses else []
    filter_params: list[str] = []
    if query:
        conditions.append(
            "concat_ws(' ', title, agent_code, provider_code, model, prompt, response, COALESCE(review_note, '')) ILIKE %s"
        )
        filter_params.append(f"%{query}%")
    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    query_params = tuple(filter_params)
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM agent_workspace_tasks{where_clause}", query_params)
        total = cur.fetchone()[0]
        cur.execute(
            f"""SELECT id, title, agent_code, provider_code, model, review_note, reviewed_at, created_at, prompt, response
                FROM agent_workspace_tasks{where_clause}
                ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s""",
            (*query_params, safe_limit, safe_offset),
        )
        rows = cur.fetchall()
    return [_serialize(row) for row in rows], total


def set_workspace_task_reviewed(
    conn: Any, task_id: int, reviewed: bool, review_note: str | None = None,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE agent_workspace_tasks
               SET reviewed_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                   review_note = CASE WHEN %s THEN %s ELSE NULL END
               WHERE id = %s
               RETURNING id, title, agent_code, provider_code, model, review_note, reviewed_at, created_at, prompt, response""",
            (reviewed, reviewed, review_note, task_id),
        )
        row = cur.fetchone()
    if not row:
        raise AgentWorkspaceError("任务不存在或已删除")
    conn.commit()
    return _serialize(row)


def delete_workspace_task(conn: Any, task_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM agent_workspace_tasks WHERE id = %s", (task_id,))
        deleted = cur.rowcount
    if not deleted:
        raise AgentWorkspaceError("任务不存在或已删除")
    conn.commit()
