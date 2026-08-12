from __future__ import annotations

from unittest.mock import MagicMock

from apps.backend.src.routers import model_providers
from apps.backend.src.services.model_gateway import ModelGatewayError


def test_failed_manual_call_keeps_provider_model_and_specific_error_code(
    client, monkeypatch
) -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    monkeypatch.setattr(model_providers, "get_db", lambda: connection)
    monkeypatch.setattr(
        model_providers,
        "invoke_agent_model",
        lambda *_args: (_ for _ in ()).throw(
            ModelGatewayError(
                "模型调用超时，请稍后重试",
                error_code="MODEL_TIMEOUT",
                provider_code="deepseek",
                model="deepseek-v4-pro",
            )
        ),
    )
    audit = MagicMock()
    monkeypatch.setattr(model_providers, "record_model_invocation", audit)

    response = client.post(
        "/api/model-providers/agent-bindings/review_agent/invoke",
        json={"prompt": "检查链路"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "模型调用超时，请稍后重试"
    assert audit.call_args.kwargs["provider_code"] == "deepseek"
    assert audit.call_args.kwargs["model"] == "deepseek-v4-pro"
    assert audit.call_args.kwargs["error_code"] == "MODEL_TIMEOUT"
