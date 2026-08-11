"""Contracts for manual, server-sourced Agent interpretations."""

from __future__ import annotations

from unittest.mock import MagicMock

from apps.backend.src.routers import agent_interpretations
from apps.backend.src.services.agent_interpretation import (
    InterpretationSource,
    InterpretationSourceError,
    build_pre_match_source,
)
from apps.backend.src.services.model_gateway import ModelReply


def _source(source_ref: str = "42") -> InterpretationSource:
    return InterpretationSource(
        "pre_match", source_ref, "解读标题", "pre_match_interpretation_agent", "后端冻结材料"
    )


def test_post_match_manual_interpretation_route_is_not_exposed() -> None:
    paths = {route.path for route in agent_interpretations.router.routes}

    assert "/api/agent-interpretations/post-match/{source_type}/{source_ref}" not in paths


def test_pre_match_interpretation_archives_server_source_and_invokes_once(
    client, monkeypatch
) -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    archived = {"id": 8, "sourceType": "pre_match", "sourceRef": "42"}
    invoke = MagicMock(return_value=ModelReply("openai", "gpt-5-mini", "需人工核验"))
    monkeypatch.setattr(agent_interpretations, "get_db", lambda: connection)
    monkeypatch.setattr(agent_interpretations, "build_pre_match_source", lambda *_: _source())
    monkeypatch.setattr(agent_interpretations, "invoke_agent_model", invoke)
    monkeypatch.setattr(
        agent_interpretations, "create_workspace_task", lambda *_args, **_kwargs: archived
    )
    audit = MagicMock()
    monkeypatch.setattr(agent_interpretations, "record_model_invocation", audit)

    response = client.post(
        "/api/agent-interpretations/pre-match/42", json={"focusQuestion": "看赔率"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "task": archived,
        "agentCode": "pre_match_interpretation_agent",
        "providerCode": "openai",
        "model": "gpt-5-mini",
    }
    invoke.assert_called_once_with(connection, "pre_match_interpretation_agent", "后端冻结材料")
    assert audit.call_args.kwargs["status"] == "succeeded"


def test_interpretation_returns_not_found_without_model_call_when_source_is_missing(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(agent_interpretations, "get_db", MagicMock())
    monkeypatch.setattr(
        agent_interpretations,
        "build_pre_match_source",
        lambda *_: (_ for _ in ()).throw(InterpretationSourceError("官方比赛不存在")),
    )
    invoke = MagicMock()
    monkeypatch.setattr(agent_interpretations, "invoke_agent_model", invoke)

    response = client.post("/api/agent-interpretations/pre-match/404", json={})

    assert response.status_code == 404
    assert response.json()["detail"] == "官方比赛不存在"
    invoke.assert_not_called()


class _Cursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = iter(rows)

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, _query: str, _params: object) -> None:
        return None

    def fetchone(self):
        return next(self.rows)

    def fetchall(self):
        return next(self.rows)


class _Connection:
    def __init__(self, rows: list[object]) -> None:
        self.cursor_instance = _Cursor(rows)

    def cursor(self) -> _Cursor:
        return self.cursor_instance


def test_pre_match_snapshot_contains_only_server_read_business_material() -> None:
    connection = _Connection(
        [
            (42, "周日001", "英超", "主队", "客队", "2026-08-02T12:00:00", "scheduled", "on_sale"),
            [("SPF", "h", 1.86, None, "2026-08-02T10:00:00")],
            [("baseline", "SPF", "h", 0.55, 0.50, 1.82, 0.02, 0.7, "2026-08-02T10:01:00")],
        ]
    )

    source = build_pre_match_source(connection, 42, "关注主胜")

    assert source.source_type == "pre_match"
    assert source.source_ref == "42"
    assert source.agent_code == "pre_match_interpretation_agent"
    assert "周日001" in source.prompt
    assert "1.86" in source.prompt
    assert "baseline" in source.prompt
    assert "关注主胜" in source.prompt
