from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.backend.src.services.model_provider_store import (
    ProviderConfigError,
    _cipher,
    list_agent_model_bindings,
    provider_catalog,
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

    assert catalog["deepseek"]["defaultBaseUrl"] == "https://api.deepseek.com"
    assert catalog["deepseek"]["recommendedModels"] == ("deepseek-v4-flash", "deepseek-v4-pro")
    assert catalog["zhipu"]["defaultModel"] == "glm-5.2"
    assert catalog["moonshot"]["defaultBaseUrl"] == "https://api.moonshot.ai/v1"
    assert catalog["perplexity"]["defaultBaseUrl"] == "https://api.perplexity.ai"
    assert catalog["gemini"]["defaultModel"] == "gemini-3.6-flash"
    assert catalog["xiaomi"]["defaultBaseUrl"] == "https://api.xiaomimimo.com/v1"
    assert catalog["xiaomi"]["recommendedModels"] == ("mimo-v2.5-pro", "mimo-v2.5")
    assert catalog["openrouter"]["recommendedModels"][1] == "anthropic/claude-opus-4.6"
    assert catalog["siliconflow"]["defaultBaseUrl"] == "https://api.siliconflow.com/v1"
    assert catalog["minimax"]["recommendedModels"][0] == "MiniMax-M2.7"
    assert catalog["xai"]["documentationUrl"].startswith("https://docs.x.ai/")


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
    def __init__(self, connection: "_SavedKeyConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "_SavedKeyCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: object = None) -> None:
        self.connection.queries.append((query, params))

    def fetchone(self) -> tuple[object, ...]:
        if "SELECT base_url" in self.connection.queries[-1][0]:
            return ("https://api.openai.com/v1", "gpt-5-mini", True)
        return (
            "openai", "OpenAI", "https://api.openai.com/v1", "gpt-5-mini", True,
            True, None, None, None, None,
        )


class _SavedKeyConnection:
    def __init__(self) -> None:
        self.queries: list[tuple[str, object]] = []
        self.committed = False

    def cursor(self) -> _SavedKeyCursor:
        return _SavedKeyCursor(self)

    def commit(self) -> None:
        self.committed = True


def test_provider_update_can_keep_encrypted_api_key() -> None:
    conn = _SavedKeyConnection()

    result = save_provider_config(conn, {
        "providerCode": "openai", "defaultModel": "gpt-5-mini", "enabled": True,
    })

    assert result["hasApiKey"] is True
    assert conn.committed is True


def test_provider_update_invalidates_test_after_connection_change() -> None:
    conn = _SavedKeyConnection()

    save_provider_config(conn, {
        "providerCode": "openai", "baseUrl": "https://models.example.test/v1",
        "defaultModel": "gpt-5-mini", "enabled": True,
    })

    query, params = conn.queries[-1]
    assert "last_test_status = CASE WHEN %s THEN NULL" in query
    assert params is not None and tuple(params)[-3:] == (True, True, True)


class _BindingCursor:
    def __enter__(self) -> "_BindingCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, _query: str) -> None:
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        return [
            ("review_agent", "openai", True, datetime.now(UTC), "OpenAI", "gpt-5-mini", True, "passed"),
        ]


class _BindingConnection:
    def cursor(self) -> _BindingCursor:
        return _BindingCursor()


def test_agent_binding_exposes_provider_test_status() -> None:
    bindings = list_agent_model_bindings(_BindingConnection())

    review_binding = next(item for item in bindings if item["agentCode"] == "review_agent")
    assert review_binding["providerTestStatus"] == "passed"
