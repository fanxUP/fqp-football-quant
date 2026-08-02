from __future__ import annotations

import pytest

from apps.backend.src.services.model_provider_store import (
    ProviderConfigError,
    _cipher,
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
