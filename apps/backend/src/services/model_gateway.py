"""Single safe invocation boundary for opt-in internal model agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.backend.src.services.model_agent_prompts import get_agent_system_instruction
from apps.backend.src.services.model_provider_store import (
    get_agent_model_binding,
    invoke_provider,
    provider_connection,
)
from apps.backend.src.services.pi_bridge import PiBridgeError


class ModelGatewayError(RuntimeError):
    """A configured model cannot safely serve the requested agent call."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "MODEL_CALL_FAILED",
        provider_code: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.provider_code = provider_code
        self.model = model


@dataclass(frozen=True)
class ModelReply:
    provider_code: str
    model: str
    content: str


def model_failure_metadata(exc: Exception) -> dict[str, str | None]:
    """Return safe diagnostic fields without persisting provider response bodies."""
    if isinstance(exc, ModelGatewayError):
        return {
            "provider_code": exc.provider_code,
            "model": exc.model,
            "error_code": exc.error_code,
        }
    return {"provider_code": None, "model": None, "error_code": "MODEL_CONFIG_ERROR"}


def invoke_agent_model(conn: Any, agent_code: str, prompt: str) -> ModelReply:
    """Invoke one explicitly enabled binding. Scheduled betting logic never calls this."""
    if not prompt.strip() or len(prompt) > 8_000:
        raise ModelGatewayError("请求内容不能为空，且不能超过 8000 个字符")
    binding = get_agent_model_binding(conn, agent_code)
    if not binding or not binding["enabled"]:
        raise ModelGatewayError("该智能代理未启用模型调用")
    if binding["last_test_status"] != "passed":
        raise ModelGatewayError("模型服务商配置变更后，请重新测试连接再试运行")
    provider_code = str(binding["provider_code"])
    model = str(binding["default_model"])
    try:
        system_instruction = get_agent_system_instruction(agent_code)
    except ValueError as exc:
        raise ModelGatewayError(str(exc)) from exc
    try:
        timeout = 60.0 if agent_code == "post_match_report_agent" else 30.0
        max_tokens = 2_400 if agent_code == "post_match_report_agent" else 800
        with provider_connection(conn) as credential_conn:
            result = invoke_provider(
                credential_conn,
                provider_code,
                prompt,
                system_instruction,
                max_tokens=max_tokens,
                timeout=timeout,
                agent_code=agent_code,
            )
        content = str(result["content"])
    except PiBridgeError as exc:
        raise ModelGatewayError(
            str(exc), error_code=exc.code, provider_code=provider_code, model=model
        ) from exc
    if not content:
        raise ModelGatewayError(
            "模型未返回可用文本",
            error_code="MODEL_EMPTY_RESPONSE",
            provider_code=provider_code,
            model=model,
        )
    return ModelReply(provider_code, model, content[:12_000])


def _http_error_detail(status: int) -> tuple[str, str]:
    if status in {401, 403}:
        return "MODEL_AUTH_FAILED", "模型服务商鉴权失败，请重新检查 API 密钥"
    if status == 404:
        return "MODEL_NOT_FOUND", "所选模型或服务地址不存在，请重新测试连接"
    if status == 429:
        return "MODEL_RATE_LIMITED", "模型服务商限额或频率受限，请稍后重试"
    if status >= 500:
        return "MODEL_PROVIDER_UNAVAILABLE", "模型服务商暂时不可用，请稍后重试"
    return "MODEL_REQUEST_REJECTED", "模型服务商拒绝请求，请检查模型名称与参数"
