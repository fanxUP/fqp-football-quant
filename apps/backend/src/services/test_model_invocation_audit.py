from __future__ import annotations

from datetime import UTC, datetime

from apps.backend.src.services.model_invocation_audit import (
    list_model_invocations,
    record_model_invocation,
)


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = rows
        self.statement = ""
        self.params = ()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=()):
        self.statement, self.params = statement, params

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows=()):
        self.cursor_instance = FakeCursor(rows)
        self.committed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True


def test_audit_persists_metadata_without_prompt_or_reply() -> None:
    conn = FakeConnection()
    record_model_invocation(
        conn,
        agent_code="doc_agent",
        provider_code="openai",
        model="gpt-5-mini",
        status="succeeded",
        prompt_length=123,
        response_length=456,
        duration_ms=78,
    )

    assert conn.committed
    assert "prompt_body" not in conn.cursor_instance.statement.lower()
    assert "response_body" not in conn.cursor_instance.statement.lower()
    assert conn.cursor_instance.params == ("doc_agent", "openai", "gpt-5-mini", "succeeded", 123, 456, 78, None)


def test_audit_list_returns_safe_public_shape() -> None:
    conn = FakeConnection([
        ("doc_agent", "openai", "gpt-5-mini", "succeeded", 10, 20, 30, None, datetime(2026, 8, 2, tzinfo=UTC)),
    ])

    rows = list_model_invocations(conn, limit=999)

    assert rows == [{
        "agentCode": "doc_agent", "providerCode": "openai", "model": "gpt-5-mini", "status": "succeeded",
        "promptLength": 10, "responseLength": 20, "durationMs": 30, "errorCode": None,
        "createdAt": "2026-08-02T00:00:00+00:00",
    }]
    assert conn.cursor_instance.params == (50,)
