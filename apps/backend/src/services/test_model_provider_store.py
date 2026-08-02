from __future__ import annotations

import pytest

from apps.backend.src.services.model_provider_store import (
    ProviderConfigError,
    _cipher,
    save_provider_config,
    validate_provider_input,
)


def test_provider_input_uses_preset_defaults() -> None:
    provider, base_url, model = validate_provider_input("openai", None, "gpt-5-mini")

    assert provider.code == "openai"
    assert base_url == "https://api.openai.com/v1"
    assert model == "gpt-5-mini"


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

    def execute(self, query: str, _params: object = None) -> None:
        self.connection.queries.append(query)

    def fetchone(self) -> tuple[object, ...]:
        if "SELECT api_key_encrypted" in self.connection.queries[-1]:
            return (True,)
        return (
            "openai", "OpenAI", "https://api.openai.com/v1", "gpt-5-mini", True,
            True, None, None, None, None,
        )


class _SavedKeyConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []
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
