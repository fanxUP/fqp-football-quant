from __future__ import annotations

from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock

import pytest

from apps.backend.src.services import model_gateway, model_provider_store
from apps.backend.src.services.model_gateway import ModelGatewayError, invoke_agent_model
from apps.backend.src.services.pi_bridge import PiBridgeError


@pytest.fixture(autouse=True)
def isolated_connection(monkeypatch):
    monkeypatch.setattr(model_gateway, "provider_connection", lambda caller: nullcontext(caller))


def _ready_binding() -> dict[str, Any]:
    return {
        "provider_code": "deepseek",
        "enabled": True,
        "default_model": "deepseek-v4-pro",
        "last_test_status": "passed",
    }


def test_report_agent_uses_longer_timeout_and_exposes_timeout_diagnostics(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(model_gateway, "get_agent_model_binding", lambda *_: _ready_binding())

    def request(*args, **kwargs):
        captured.update(kwargs)
        raise PiBridgeError("timeout", "MODEL_TIMEOUT")

    monkeypatch.setattr(model_gateway, "invoke_provider", request)
    with pytest.raises(ModelGatewayError) as raised:
        invoke_agent_model(object(), "post_match_report_agent", "生成复盘")
    assert captured["timeout"] == 60
    assert captured["agent_code"] == "post_match_report_agent"
    assert raised.value.error_code == "MODEL_TIMEOUT"
    assert raised.value.provider_code == "deepseek"
    assert raised.value.model == "deepseek-v4-pro"


def test_report_agent_reserves_enough_output_tokens_for_structured_sections(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(model_gateway, "get_agent_model_binding", lambda *_: _ready_binding())

    def request(*args, **kwargs):
        captured.update(kwargs)
        return {"content": "复盘完成"}

    monkeypatch.setattr(model_gateway, "invoke_provider", request)
    reply = invoke_agent_model(object(), "post_match_report_agent", "生成五部分复盘")
    assert reply.content == "复盘完成"
    assert captured["max_tokens"] == 2400


def test_provider_test_validates_selected_model_through_pi(monkeypatch) -> None:
    invoke = MagicMock(return_value={"content": "OK", "version": None})
    monkeypatch.setattr(model_provider_store, "invoke_provider", invoke)
    conn = MagicMock()
    result = model_provider_store.test_provider_config(conn, "deepseek")
    assert result["status"] == "passed"
    assert "所选模型" in result["message"]
    assert invoke.call_args.args[1] == "deepseek"
    assert invoke.call_args.kwargs["require_ready"] is False
    assert invoke.call_args.kwargs["max_tokens"] == 64
