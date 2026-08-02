"""Admin API for configurable language-model providers."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.backend.src.db import get_db
from apps.backend.src.services.model_gateway import ModelGatewayError, invoke_agent_model
from apps.backend.src.services.model_provider_store import (
    ProviderConfigError,
    list_agent_model_bindings,
    list_provider_configs,
    provider_catalog,
    save_agent_model_binding,
    save_provider_config,
    test_provider_config,
)

router = APIRouter(prefix="/api/model-providers", tags=["model-providers"])


class ProviderConfigRequest(BaseModel):
    providerCode: str = Field(min_length=2, max_length=64)
    displayName: str | None = Field(default=None, max_length=80)
    baseUrl: str | None = Field(default=None, max_length=300)
    defaultModel: str = Field(min_length=1, max_length=160)
    apiKey: str | None = Field(default=None, max_length=4096)
    enabled: bool = True


class AgentBindingRequest(BaseModel):
    providerCode: str = Field(min_length=2, max_length=64)
    enabled: bool = False


class AgentInvokeRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)


def _raise_config_error(exc: ProviderConfigError) -> None:
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/catalog")
def get_provider_catalog():
    """Return public presets; credentials are deliberately not part of this response."""
    return {"providers": provider_catalog()}


@router.get("")
def get_provider_configs():
    with get_db() as conn:
        configs = list_provider_configs(conn)
    return {"providers": configs}


@router.get("/agent-bindings")
def get_agent_bindings():
    with get_db() as conn:
        return {"bindings": list_agent_model_bindings(conn)}


@router.put("/agent-bindings/{agent_code}")
def put_agent_binding(agent_code: str, body: AgentBindingRequest):
    try:
        with get_db() as conn:
            binding = save_agent_model_binding(conn, agent_code, body.providerCode, body.enabled)
    except ProviderConfigError as exc:
        _raise_config_error(exc)
    return {"binding": binding}


@router.post("/agent-bindings/{agent_code}/invoke")
def invoke_agent_binding(agent_code: str, body: AgentInvokeRequest):
    """Explicit manual call only; it is never part of the recommendation scheduler."""
    try:
        with get_db() as conn:
            result = invoke_agent_model(conn, agent_code, body.prompt)
    except (ProviderConfigError, ModelGatewayError) as exc:
        _raise_config_error(exc)
    return {"agentCode": agent_code, "providerCode": result.provider_code, "model": result.model, "content": result.content}


@router.put("/{provider_code}")
def put_provider_config(provider_code: str, body: ProviderConfigRequest):
    if provider_code != body.providerCode:
        raise HTTPException(status_code=400, detail="路径服务商与请求内容不一致")
    try:
        with get_db() as conn:
            provider = save_provider_config(conn, body.model_dump())
    except ProviderConfigError as exc:
        _raise_config_error(exc)
    return {"provider": provider}


@router.post("/{provider_code}/test")
def test_provider(provider_code: str):
    try:
        with get_db() as conn:
            result = test_provider_config(conn, provider_code)
    except ProviderConfigError as exc:
        _raise_config_error(exc)
    return result
