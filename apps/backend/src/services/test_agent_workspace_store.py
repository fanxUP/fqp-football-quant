from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.backend.src.services.agent_workspace_store import (
    AgentWorkspaceError,
    list_workspace_tasks,
    set_workspace_task_reviewed,
)


class _Cursor:
    def __init__(self, conn: "_Connection") -> None:
        self.conn = conn

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: object = None) -> None:
        self.conn.queries.append((query, params))

    def fetchall(self):
        return self.conn.rows

    def fetchone(self):
        return self.conn.row


class _Connection:
    def __init__(self, rows=(), row=None) -> None:
        self.rows = rows
        self.row = row
        self.queries: list[tuple[str, object]] = []
        self.committed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.committed = True


def _task_row(reviewed_at=None):
    return (7, "结构化复盘", "review_agent", "openai", "gpt-5-mini", reviewed_at,
            datetime(2026, 8, 2, tzinfo=UTC), "材料", "结果")


def test_workspace_tasks_return_untrusted_content_as_plain_data() -> None:
    conn = _Connection(rows=[_task_row()])

    tasks = list_workspace_tasks(conn, limit=99)

    assert tasks[0]["prompt"] == "材料"
    assert tasks[0]["response"] == "结果"
    assert tasks[0]["reviewedAt"] is None
    assert conn.queries[-1][1] == (50,)


def test_workspace_review_uses_parameterized_update() -> None:
    conn = _Connection(row=_task_row(datetime(2026, 8, 2, tzinfo=UTC)))

    task = set_workspace_task_reviewed(conn, 7, True)

    assert task["reviewedAt"] == "2026-08-02T00:00:00+00:00"
    assert conn.committed
    assert conn.queries[-1][1] == (True, 7)


def test_workspace_review_rejects_missing_task() -> None:
    with pytest.raises(AgentWorkspaceError, match="不存在"):
        set_workspace_task_reviewed(_Connection(row=None), 404, True)
