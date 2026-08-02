from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.backend.src.app import create_app
from apps.backend.src.routers.agent_workspace import WorkspaceComparisonRequest
from apps.backend.src.services.agent_workspace_store import (
    AgentWorkspaceError,
    create_workspace_task,
    get_workspace_comparison,
    list_workspace_comparison_tasks,
    list_workspace_task_page,
    list_workspace_task_review_events,
    list_workspace_tasks,
    set_workspace_comparison_completed,
    set_workspace_comparison_reviewed,
    set_workspace_task_reviewed,
)


class _Cursor:
    def __init__(self, conn: _Connection) -> None:
        self.conn = conn

    def __enter__(self) -> _Cursor:
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
            datetime(2026, 8, 2, tzinfo=UTC), "材料", "结果", "comparison-001", "pre_match", "42")


def test_workspace_tasks_return_untrusted_content_as_plain_data() -> None:
    conn = _Connection(rows=[_task_row()])

    tasks = list_workspace_tasks(conn, limit=99)

    assert tasks[0]["prompt"] == "材料"
    assert tasks[0]["response"] == "结果"
    assert tasks[0]["reviewNote"] == "已核对来源"
    assert tasks[0]["reviewedAt"] is None
    assert tasks[0]["comparisonId"] == "comparison-001"
    assert tasks[0]["sourceType"] == "pre_match"
    assert tasks[0]["sourceRef"] == "42"
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


def test_workspace_comparison_returns_only_its_tasks_in_creation_order() -> None:
    conn = _Connection(rows=[_task_row(), _task_row()])

    tasks = list_workspace_comparison_tasks(conn, "comparison-001")

    assert [task["comparisonId"] for task in tasks] == ["comparison-001", "comparison-001"]
    assert "comparison_id = %s" in conn.queries[0][0]
    assert conn.queries[0][1] == ("comparison-001",)


def test_workspace_comparison_exposes_requested_and_completed_counts() -> None:
    comparison_row = (
        "comparison-001", ["review_agent", "doc_agent", "data_agent"], 3, 2, 1, "completed",
        datetime(2026, 8, 2, tzinfo=UTC), datetime(2026, 8, 2, tzinfo=UTC), None, None,
    )
    conn = _Connection(row=comparison_row)

    comparison = get_workspace_comparison(conn, "comparison-001")

    assert comparison == {
        "id": "comparison-001", "requestedAgentCodes": ["review_agent", "doc_agent", "data_agent"],
        "requestedCount": 3, "succeededCount": 2, "failedCount": 1, "status": "completed",
        "createdAt": "2026-08-02T00:00:00+00:00", "completedAt": "2026-08-02T00:00:00+00:00",
        "reviewNote": None, "reviewedAt": None,
    }
    assert conn.queries[0][1] == ("comparison-001",)

    conn = _Connection(row=comparison_row)
    completed = set_workspace_comparison_completed(conn, "comparison-001", succeeded_count=2, failed_count=1)

    assert completed["failedCount"] == 1
    assert conn.committed
    assert conn.queries[0][1] == (2, 1, "comparison-001")


def test_workspace_comparison_can_save_a_human_conclusion() -> None:
    comparison_row = (
        "comparison-001", ["review_agent", "doc_agent"], 2, 2, 0, "completed",
        datetime(2026, 8, 2, tzinfo=UTC), datetime(2026, 8, 2, tzinfo=UTC),
        "人工结论：继续核对赛程。", datetime(2026, 8, 2, tzinfo=UTC),
    )
    conn = _Connection(row=comparison_row)

    comparison = set_workspace_comparison_reviewed(conn, "comparison-001", "人工结论：继续核对赛程。")

    assert comparison["reviewNote"] == "人工结论：继续核对赛程。"
    assert comparison["reviewedAt"] == "2026-08-02T00:00:00+00:00"
    assert conn.queries[0][1] == ("人工结论：继续核对赛程。", "comparison-001")


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


def test_workspace_comparison_requires_two_distinct_agent_bindings() -> None:
    with pytest.raises(ValueError, match="至少选择两个"):
        WorkspaceComparisonRequest.model_validate({
            "agentCode": "review_agent", "title": "对比", "prompt": "材料",
            "targetAgentCodes": ["review_agent"],
        })


def test_workspace_task_archives_immutable_business_source_reference() -> None:
    conn = _Connection(row=_task_row())

    task = create_workspace_task(
        conn, title="赛前解读：周日001", agent_code="pre_match_interpretation_agent",
        provider_code="openai", model="gpt-5-mini", prompt="官方比赛材料", response="仅供人工核验",
        source_type="pre_match", source_ref="42",
    )

    assert task["sourceType"] == "pre_match"
    assert task["sourceRef"] == "42"
    assert "source_type, source_ref" in conn.queries[0][0]
    assert conn.queries[0][1] == (
        "赛前解读：周日001", "pre_match_interpretation_agent", "openai", "gpt-5-mini",
        "官方比赛材料", "仅供人工核验", None, "pre_match", "42",
    )

    request = WorkspaceComparisonRequest.model_validate({
        "agentCode": "review_agent", "title": "对比", "prompt": "材料",
        "targetAgentCodes": ["review_agent", "doc_agent"],
    })

    assert request.target_agent_codes == ["review_agent", "doc_agent"]

    with pytest.raises(ValueError, match="不支持"):
        WorkspaceComparisonRequest.model_validate({
            "agentCode": "review_agent", "title": "对比", "prompt": "材料",
            "targetAgentCodes": ["review_agent", "unknown_agent"],
        })
