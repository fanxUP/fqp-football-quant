from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.backend.src.services.model_provider_store import (
    AGENT_MODEL_OPTIONS,
    ProviderConfigError,
    _cipher,
    list_agent_model_bindings,
    provider_catalog,
    save_agent_model_binding,
    save_provider_config,
    validate_provider_input,
)


def test_provider_input_uses_preset_defaults() -> None:
    provider, base_url, model = validate_provider_input("openai", None, "gpt-5-mini")

    assert provider.code == "openai"
    assert base_url == "https://api.openai.com/v1"
    assert model == "gpt-5-mini"


def test_provider_catalog_exposes_current_presets_and_official_documentation() -> None:
    catalog = {item["providerCode"]: item for item in provider_catalog()}

    assert catalog["openai"]["engine"] == "pi-ai"
    assert "oauth" in catalog["openai"]["authMethods"]
    assert catalog["deepseek"]["authMethods"] == ["api_key"]
    assert catalog["openrouter"]["modelCount"] > 100
    assert catalog["gemini"]["modelCount"] > 0
    assert catalog["openai_compatible"]["authMethods"] == ["api_key", "none"]


def test_provider_input_rejects_unsafe_base_url() -> None:
    with pytest.raises(ProviderConfigError, match="完整"):
        validate_provider_input("openai", "api.example.com", "example")


def test_provider_keys_are_encrypted_with_server_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "FQP_PROVIDER_ENCRYPTION_KEY", "unit-test-private-secret-at-least-32-characters"
    )

    encrypted = _cipher().encrypt(b"sk-never-store-plain")

    assert b"sk-never-store-plain" not in encrypted
    assert _cipher().decrypt(encrypted) == b"sk-never-store-plain"


class _SavedKeyCursor:
    def __init__(self, connection: _SavedKeyConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _SavedKeyCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        self.connection.queries.append((query, params))

    def fetchone(self) -> tuple[object, ...]:
        return (
            "openai",
            "OpenAI",
            "https://api.openai.com/v1",
            "gpt-5-mini",
            True,
            "encrypted-key",
            None,
            None,
            None,
            None,
            "api_key",
            None,
            None,
        )


class _SavedKeyConnection:
    def __init__(self) -> None:
        self.queries: list[tuple[str, tuple[object, ...] | None]] = []
        self.committed = False

    def cursor(self) -> _SavedKeyCursor:
        return _SavedKeyCursor(self)

    def commit(self) -> None:
        self.committed = True


def test_provider_update_can_keep_encrypted_api_key() -> None:
    conn = _SavedKeyConnection()

    result = save_provider_config(
        conn,
        {
            "providerCode": "openai",
            "defaultModel": "gpt-5-mini",
            "enabled": True,
        },
    )

    assert result["hasApiKey"] is True
    assert result["apiKeyMask"] == "••••••••••••"
    assert conn.committed is True


def test_provider_update_invalidates_test_after_connection_change() -> None:
    conn = _SavedKeyConnection()

    save_provider_config(
        conn,
        {
            "providerCode": "openai",
            "baseUrl": "https://models.example.test/v1",
            "defaultModel": "gpt-5-mini",
            "enabled": True,
        },
    )

    query, params = conn.queries[-1]
    assert "last_test_status = CASE WHEN %s THEN NULL" in query
    assert params is not None and tuple(params)[-3:] == (True, True, True)


class _BindingCursor:
    def __enter__(self) -> _BindingCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, _query: str) -> None:
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        return [
            (
                "review_agent",
                "openai",
                True,
                datetime.now(UTC),
                "OpenAI",
                "gpt-5-mini",
                True,
                "passed",
            ),
        ]


class _BindingConnection:
    def cursor(self) -> _BindingCursor:
        return _BindingCursor()


def test_agent_binding_exposes_provider_test_status() -> None:
    bindings = list_agent_model_bindings(_BindingConnection())

    review_binding = next(item for item in bindings if item["agentCode"] == "review_agent")
    assert review_binding["providerTestStatus"] == "passed"


def test_interpretation_agents_are_independently_bindable() -> None:
    assert AGENT_MODEL_OPTIONS["pre_match_interpretation_agent"] == "赛前解读 Agent"
    assert AGENT_MODEL_OPTIONS["post_match_report_agent"] == "自动赛后报告 Agent"
    assert AGENT_MODEL_OPTIONS["news_extraction_agent"] == "新闻事件提取 Agent"
    assert "post_match_review_agent" not in AGENT_MODEL_OPTIONS


class _LocalBindingCursor:
    def __init__(self, connection: _LocalBindingConnection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.connection.query = query
        self.connection.params = params

    def fetchone(self) -> tuple[object, ...]:
        return ("ollama", True, True, "passed")


class _LocalBindingConnection:
    def __init__(self) -> None:
        self.query = ""
        self.params: tuple[object, ...] = ()

    def cursor(self) -> _LocalBindingCursor:
        return _LocalBindingCursor(self)

    def commit(self) -> None:
        return None


def test_local_provider_can_enable_agent_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _LocalBindingConnection()
    monkeypatch.setattr(
        "apps.backend.src.services.model_provider_store.list_agent_model_bindings",
        lambda _conn: [{"agentCode": "review_agent", "enabled": True}],
    )

    result = save_agent_model_binding(connection, "review_agent", "ollama", True)

    assert result["enabled"] is True
