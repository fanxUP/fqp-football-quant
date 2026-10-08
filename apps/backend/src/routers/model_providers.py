"""Admin API for configurable language-model providers."""

from __future__ import annotations

from time import perf_counter

from fastapi import APIRouter, HTTPException, Query, Request
from psycopg2.errors import LockNotAvailable
from pydantic import BaseModel, Field

from apps.backend.src.db import get_db
from apps.backend.src.services.model_gateway import (
    ModelGatewayError,
    invoke_agent_model,
    model_failure_metadata,
)
from apps.backend.src.services.model_invocation_audit import (
    list_model_invocations,
    record_model_invocation,
)
from apps.backend.src.services.model_provider_store import (
    ProviderConfigError,
    list_agent_model_bindings,
    list_provider_configs,
    provider_catalog,
    provider_models,
    save_agent_model_binding,
    save_provider_config,
    test_provider_config,
)
from apps.backend.src.services.pi_bridge import PiBridgeError
from apps.backend.src.services.pi_login import (
    disconnect_provider,
    login_status,
    session_owner,
    start_login,
)

router = APIRouter(prefix="/api/model-providers", tags=["model-providers"])


class ProviderConfigRequest(BaseModel):
    providerCode: str = Field(min_length=2, max_length=64)
    displayName: str | None = Field(default=None, max_length=80)
    baseUrl: str | None = Field(default=None, max_length=300)
    defaultModel: str = Field(min_length=1, max_length=160)
    apiKey: str | None = Field(default=None, max_length=4096)
    enabled: bool = True
    authType: str | None = Field(default=None, pattern="^(api_key|oauth|none)$")
    apiProtocol: str | None = Field(default=None, max_length=64)
    providerEnv: dict[str, str] | None = None


class LoginInputRequest(BaseModel):
    promptId: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=4096)


def _login_owner(request: Request) -> str:
    cookie = request.cookies.get("fqp_session")
    if not cookie:
        raise HTTPException(status_code=401, detail="账号登录需要当前系统登录会话")
    return session_owner(cookie)


class AgentBindingRequest(BaseModel):
    providerCode: str = Field(min_length=2, max_length=64)
    enabled: bool = False


class AgentInvokeRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)


def _raise_config_error(exc: ProviderConfigError | ModelGatewayError) -> None:
    raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/catalog")
def get_provider_catalog():
    """Return public presets; credentials are deliberately not part of this response."""
    try:
        return {"providers": provider_catalog(), "engine": "pi-ai", "version": "1.1.0"}
    except PiBridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
    except LockNotAvailable as exc:
        raise HTTPException(status_code=409, detail="凭据正在使用或更新，请稍后重试") from exc
    except ProviderConfigError as exc:
        _raise_config_error(exc)
    return {"binding": binding}


@router.post("/agent-bindings/{agent_code}/invoke")
def invoke_agent_binding(agent_code: str, body: AgentInvokeRequest):
    """Explicit manual call only; it is never part of the recommendation scheduler."""
    started_at = perf_counter()
    try:
        with get_db() as conn:
            result = invoke_agent_model(conn, agent_code, body.prompt)
            record_model_invocation(
                conn,
                agent_code=agent_code,
                provider_code=result.provider_code,
                model=result.model,
                status="succeeded",
                prompt_length=len(body.prompt),
                response_length=len(result.content),
                duration_ms=round((perf_counter() - started_at) * 1000),
            )
    except (ProviderConfigError, ModelGatewayError) as exc:
        failure = model_failure_metadata(exc)
        with get_db() as conn:
            record_model_invocation(
                conn,
                agent_code=agent_code,
                provider_code=failure["provider_code"],
                model=failure["model"],
                status="failed",
                prompt_length=len(body.prompt),
                response_length=0,
                duration_ms=round((perf_counter() - started_at) * 1000),
                error_code=failure["error_code"],
            )
        _raise_config_error(exc)
    return {
        "agentCode": agent_code,
        "providerCode": result.provider_code,
        "model": result.model,
        "content": result.content,
    }


@router.get("/invocations")
def get_model_invocations(limit: int = Query(30, ge=1, le=50)):
    """Return recent metadata-only manual-call audit entries."""
    with get_db() as conn:
        invocations = list_model_invocations(conn, limit)
    return {"invocations": invocations, "total": len(invocations)}


@router.get("/{provider_code}/models")
def get_provider_models(
    provider_code: str,
    q: str = Query("", max_length=160),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
):
    try:
        return provider_models(provider_code, q, limit, offset)
    except ProviderConfigError as exc:
        _raise_config_error(exc)
    except PiBridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{provider_code}/login")
def post_login(provider_code: str, body: ProviderConfigRequest, request: Request):
    owner = _login_owner(request)
    if provider_code != body.providerCode:
        raise HTTPException(status_code=400, detail="路径服务商与请求内容不一致")
    try:
        return start_login(owner, provider_code, body.model_dump(exclude={"apiKey", "providerEnv"}))
    except ProviderConfigError as exc:
        _raise_config_error(exc)
    except PiBridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/logins/{login_id}")
def get_login(login_id: str, request: Request):
    try:
        return login_status(_login_owner(request), login_id)
    except ProviderConfigError as exc:
        _raise_config_error(exc)


@router.post("/logins/{login_id}/input")
def post_login_input(login_id: str, body: LoginInputRequest, request: Request):
    try:
        return login_status(
            _login_owner(request), login_id, prompt_id=body.promptId, value=body.value
        )
    except ProviderConfigError as exc:
        _raise_config_error(exc)


@router.delete("/logins/{login_id}")
def delete_login(login_id: str, request: Request):
    try:
        return login_status(_login_owner(request), login_id, cancel=True)
    except ProviderConfigError as exc:
        _raise_config_error(exc)


@router.delete("/{provider_code}/credential")
def delete_credential(provider_code: str):
    try:
        with get_db() as conn:
            disconnect_provider(conn, provider_code)
    except LockNotAvailable as exc:
        raise HTTPException(status_code=409, detail="凭据正在使用或更新，请稍后重试") from exc
    return {"status": "disconnected"}


@router.put("/{provider_code}")
def put_provider_config(provider_code: str, body: ProviderConfigRequest):
    if provider_code != body.providerCode:
        raise HTTPException(status_code=400, detail="路径服务商与请求内容不一致")
    try:
        with get_db() as conn:
            provider = save_provider_config(conn, body.model_dump())
    except LockNotAvailable as exc:
        raise HTTPException(status_code=409, detail="凭据正在使用或更新，请稍后重试") from exc
    except ProviderConfigError as exc:
        _raise_config_error(exc)
    except PiBridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"provider": provider}


@router.post("/{provider_code}/test")
def test_provider(provider_code: str):
    try:
        with get_db() as conn:
            result = test_provider_config(conn, provider_code)
    except ProviderConfigError as exc:
        _raise_config_error(exc)
    except PiBridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result
