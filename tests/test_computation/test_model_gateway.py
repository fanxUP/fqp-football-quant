from __future__ import annotations

from typing import Any

import httpx
import pytest

from apps.backend.src.services import model_gateway, model_provider_store
from apps.backend.src.services.model_gateway import ModelGatewayError, invoke_agent_model


class _Client:
    timeout: float | None = None

    def __init__(self, *, timeout: float, follow_redirects: bool) -> None:
        self.__class__.timeout = timeout
        assert follow_redirects is False

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _ready_binding() -> dict[str, Any]:
    return {
        "agent_code": "post_match_report_agent",
        "provider_code": "deepseek",
        "enabled": True,
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-pro",
        "api_key_encrypted": "encrypted",
        "protocol": "openai",
        "last_test_status": "passed",
    }


def test_report_agent_uses_longer_timeout_and_exposes_timeout_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_gateway, "get_agent_model_binding", lambda *_: _ready_binding())
    monkeypatch.setattr(model_gateway, "_decrypt_key", lambda _value: "key")
    monkeypatch.setattr(model_gateway.httpx, "Client", _Client)
    monkeypatch.setattr(
        model_gateway,
        "_request_completion",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    )

    with pytest.raises(ModelGatewayError) as raised:
        invoke_agent_model(object(), "post_match_report_agent", "生成复盘")

    assert _Client.timeout == 60.0
    assert raised.value.error_code == "MODEL_TIMEOUT"
    assert raised.value.provider_code == "deepseek"
    assert raised.value.model == "deepseek-v4-pro"


class _ProbeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"choices": [{"message": {"content": "OK"}}]}


class _ProbeClient:
    get_calls = 0
    post_calls = 0

    def __init__(self, **_kwargs: Any) -> None:
        return None

    def __enter__(self) -> _ProbeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, *_args: Any, **_kwargs: Any) -> _ProbeResponse:
        self.__class__.get_calls += 1
        return _ProbeResponse()

    def post(self, *_args: Any, **_kwargs: Any) -> _ProbeResponse:
        self.__class__.post_calls += 1
        return _ProbeResponse()


def test_provider_test_validates_the_selected_model_with_a_minimal_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ProbeClient.get_calls = 0
    _ProbeClient.post_calls = 0
    monkeypatch.setattr(model_provider_store.httpx, "Client", _ProbeClient)
    provider = model_provider_store.PROVIDERS["deepseek"]

    status, message = model_provider_store._probe_provider(
        provider,
        "https://api.deepseek.com",
        "deepseek-v4-pro",
        "key",
    )

    assert status == "passed"
    assert "所选模型" in message
    assert _ProbeClient.post_calls == 1
    assert _ProbeClient.get_calls == 0
