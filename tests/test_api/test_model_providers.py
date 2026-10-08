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


def test_pi_catalog_returns_actual_engine_and_model_pagination(client) -> None:
    result = client.get("/api/model-providers/catalog")
    assert result.status_code == 200
    assert result.json()["engine"] == "pi-ai"
    models = client.get("/api/model-providers/openrouter/models?limit=2&offset=2")
    assert models.status_code == 200
    assert len(models.json()["models"]) == 2
    assert models.json()["total"] > 100


def test_oauth_endpoints_require_session_and_bound_owner(client, monkeypatch) -> None:
    assert client.get("/api/model-providers/logins/unknown").status_code == 401
    client.cookies.set("fqp_session", "unit-session")
    owner = []

    def status(session_owner, login_id, **kwargs):
        owner.append(session_owner)
        return {"status": "waiting"}

    monkeypatch.setattr(model_providers, "login_status", status)
    assert client.get("/api/model-providers/logins/unknown").status_code == 200
    assert owner[0] != "unit-session" and len(owner[0]) == 64


def test_login_payload_rejects_mismatched_provider_without_upstream(client) -> None:
    client.cookies.set("fqp_session", "unit-session")
    result = client.post(
        "/api/model-providers/openai/login",
        json={"providerCode": "anthropic", "defaultModel": "claude-test"},
    )
    assert result.status_code == 400


def test_model_list_rejects_oversized_page(client) -> None:
    assert client.get("/api/model-providers/openai/models?limit=101").status_code == 422
