from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.backend.src.services.agent_workspace_store import (
    AgentWorkspaceError,
    list_workspace_task_page,
    list_workspace_task_review_events,
    list_workspace_tasks,
    set_workspace_task_reviewed,
)
from apps.backend.src.app import create_app


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
    return (7, "结构化复盘", "review_agent", "openai", "gpt-5-mini", "已核对来源", reviewed_at,
            datetime(2026, 8, 2, tzinfo=UTC), "材料", "结果")


def test_workspace_tasks_return_untrusted_content_as_plain_data() -> None:
    conn = _Connection(rows=[_task_row()])

    tasks = list_workspace_tasks(conn, limit=99)

    assert tasks[0]["prompt"] == "材料"
    assert tasks[0]["response"] == "结果"
    assert tasks[0]["reviewNote"] == "已核对来源"
    assert tasks[0]["reviewedAt"] is None
    assert conn.queries[-1][1] == (50,)


def test_workspace_task_page_uses_fixed_status_clause_and_parameterized_paging() -> None:
    conn = _Connection(rows=[_task_row()], row=(3,))

    tasks, total = list_workspace_task_page(conn, limit=99, offset=4, review_status="pending")

    assert tasks[0]["id"] == 7
    assert total == 3
    assert "reviewed_at IS NULL" in conn.queries[0][0]
    assert conn.queries[1][1] == (50, 4)


def test_workspace_task_page_parameterizes_full_archive_keyword() -> None:
    conn = _Connection(rows=[_task_row()], row=(1,))

    tasks, total = list_workspace_task_page(conn, query="' OR 1=1 --")

    assert tasks[0]["id"] == 7
    assert total == 1
    assert "ILIKE %s" in conn.queries[0][0]
    assert conn.queries[0][1] == ("%' OR 1=1 --%",)
    assert conn.queries[1][1] == ("%' OR 1=1 --%", 20, 0)


def test_workspace_review_uses_parameterized_update() -> None:
    conn = _Connection(row=_task_row(datetime(2026, 8, 2, tzinfo=UTC)))

    task = set_workspace_task_reviewed(conn, 7, True, "已核验数据来源")

    assert task["reviewedAt"] == "2026-08-02T00:00:00+00:00"
    assert conn.committed
    assert conn.queries[-2][1] == (True, True, "已核验数据来源", 7)
    assert conn.queries[-1][1] == (7, "confirmed", "已核验数据来源")


def test_workspace_review_rejects_missing_task() -> None:
    with pytest.raises(AgentWorkspaceError, match="不存在"):
        set_workspace_task_reviewed(_Connection(row=None), 404, True)


def test_workspace_review_history_requires_existing_task_and_uses_parameterized_query() -> None:
    event_row = (1, "confirmed", "已核对来源", datetime(2026, 8, 2, tzinfo=UTC))
    conn = _Connection(rows=[event_row], row=(1,))

    events = list_workspace_task_review_events(conn, 7, limit=999)

    assert events[0]["action"] == "confirmed"
    assert events[0]["reviewNote"] == "已核对来源"
    assert conn.queries[0][1] == (7,)
    assert conn.queries[1][1] == (7, 100)


def test_workspace_task_routes_reject_non_positive_task_ids_at_the_api_boundary() -> None:
    paths = create_app().openapi()["paths"]

    for path, method in (
        ("/api/agent-workspace/tasks/{task_id}", "patch"),
        ("/api/agent-workspace/tasks/{task_id}/reviews", "get"),
        ("/api/agent-workspace/tasks/{task_id}", "delete"),
    ):
        parameter = next(item for item in paths[path][method]["parameters"] if item["name"] == "task_id")
        assert parameter["schema"]["minimum"] == 1
