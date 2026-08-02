"""Encrypted persistence and safe connectivity checks for language-model providers."""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken


@dataclass(frozen=True)
class ProviderDefinition:
    code: str
    name: str
    protocol: str
    default_base_url: str
    default_model: str
    recommended_models: tuple[str, ...]
    capabilities: tuple[str, ...]
    documentation_url: str
    requires_api_key: bool = True


PROVIDERS: dict[str, ProviderDefinition] = {
    "openai": ProviderDefinition(
        "openai",
        "OpenAI",
        "openai",
        "https://api.openai.com/v1",
        "gpt-5.2",
        ("gpt-5.2", "gpt-5-mini"),
        ("analysis", "coding", "vision"),
        "https://platform.openai.com/docs/api-reference/models",
    ),
    "anthropic": ProviderDefinition(
        "anthropic",
        "Anthropic",
        "anthropic",
        "https://api.anthropic.com/v1",
        "claude-sonnet-4-5",
        ("claude-sonnet-4-5", "claude-haiku-4-5"),
        ("analysis", "coding", "vision"),
        "https://docs.anthropic.com/en/api/models-list",
    ),
    "gemini": ProviderDefinition(
        "gemini",
        "Google Gemini",
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta",
        "gemini-3.6-flash",
        ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-pro", "gemini-2.5-flash"),
        ("analysis", "vision"),
        "https://ai.google.dev/gemini-api/docs/models",
    ),
    "deepseek": ProviderDefinition(
        "deepseek",
        "DeepSeek",
        "openai",
        "https://api.deepseek.com",
        "deepseek-v4-flash",
        ("deepseek-v4-flash", "deepseek-v4-pro"),
        ("analysis", "coding"),
        "https://api-docs.deepseek.com/quick_start/pricing",
    ),
    "qwen": ProviderDefinition(
        "qwen",
        "阿里云百炼（通义千问）",
        "openai",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen3.7-plus",
        ("qwen3.7-max", "qwen3.7-plus", "qwen3.6-plus"),
        ("analysis", "coding", "vision"),
        "https://help.aliyun.com/zh/model-studio/base-url",
    ),
    "openrouter": ProviderDefinition(
        "openrouter",
        "OpenRouter",
        "openai",
        "https://openrouter.ai/api/v1",
        "openai/gpt-5.2",
        ("openai/gpt-5.2", "anthropic/claude-sonnet-4.5", "google/gemini-3.6-flash-preview"),
        ("analysis", "coding", "vision"),
        "https://openrouter.ai/docs/quickstart",
    ),
    "siliconflow": ProviderDefinition(
        "siliconflow",
        "硅基流动",
        "openai",
        "https://api.siliconflow.cn/v1",
        "deepseek-ai/DeepSeek-V3",
        ("deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "Qwen/Qwen3-32B"),
        ("analysis", "coding"),
        "https://docs.siliconflow.cn/cn/api-reference/chat-completions/chat-completions",
    ),
    "zhipu": ProviderDefinition(
        "zhipu",
        "智谱 AI（GLM）",
        "openai",
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-4.7",
        ("glm-4.7", "glm-4.5-air", "glm-4.5-flash"),
        ("analysis", "coding", "vision"),
        "https://open.bigmodel.cn/dev/api",
    ),
    "moonshot": ProviderDefinition(
        "moonshot",
        "Moonshot AI（月之暗面）",
        "openai",
        "https://api.moonshot.cn/v1",
        "kimi-k2.5",
        ("kimi-k2.5", "kimi-k2-turbo-preview", "moonshot-v1-32k"),
        ("analysis", "coding"),
        "https://platform.moonshot.cn/docs/api-reference",
    ),
    "minimax": ProviderDefinition(
        "minimax",
        "MiniMax",
        "openai",
        "https://api.minimaxi.com/v1",
        "MiniMax-M2.7",
        ("MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5"),
        ("analysis", "coding"),
        "https://platform.minimaxi.com/docs/api-reference/text-chat-openai",
    ),
    "groq": ProviderDefinition(
        "groq",
        "Groq",
        "openai",
        "https://api.groq.com/openai/v1",
        "openai/gpt-oss-120b",
        ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"),
        ("analysis", "coding"),
        "https://console.groq.com/docs/openai",
    ),
    "xai": ProviderDefinition(
        "xai",
        "xAI（Grok）",
        "openai",
        "https://api.x.ai/v1",
        "grok-4.3-latest",
        ("grok-4.3-latest", "grok-latest", "grok-420-reasoning"),
        ("analysis", "coding", "vision"),
        "https://docs.x.ai/developers/rest-api-reference/inference/chat",
    ),
    "perplexity": ProviderDefinition(
        "perplexity",
        "Perplexity",
        "openai",
        "https://api.perplexity.ai/v1",
        "sonar",
        ("sonar", "sonar-pro"),
        ("analysis",),
        "https://docs.perplexity.ai/docs/agent-api/openai-compatibility",
    ),
    "ollama": ProviderDefinition(
        "ollama",
        "Ollama（本地）",
        "ollama",
        "http://127.0.0.1:11434",
        "qwen3:8b",
        ("qwen3:8b", "llama3.3:70b", "deepseek-r1:8b"),
        ("analysis", "coding"),
        "https://docs.ollama.com/api",
        False,
    ),
    "openai_compatible": ProviderDefinition(
        "openai_compatible", "自定义 OpenAI 兼容服务", "openai", "", "",
        (), ("analysis", "coding"), "https://platform.openai.com/docs/api-reference/chat",
    ),
}

AGENT_MODEL_OPTIONS: dict[str, str] = {
    "orchestrator_agent": "任务编排 Agent",
    "review_agent": "复盘 Agent",
    "doc_agent": "文档 Agent",
}


class ProviderConfigError(ValueError):
    """Raised when a provider configuration is unsafe or incomplete."""


def _cipher() -> Fernet:
    secret = os.getenv("FQP_PROVIDER_ENCRYPTION_KEY", "").strip()
    if len(secret) < 32:
        raise ProviderConfigError("未配置 FQP_PROVIDER_ENCRYPTION_KEY，无法安全保存 API 密钥")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _validate_url(value: str, *, allow_empty: bool = False) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized and allow_empty:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderConfigError("服务地址必须是完整的 http:// 或 https:// 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderConfigError("服务地址不能包含账号、查询参数或片段")
    return normalized


def validate_provider_input(
    provider_code: str, base_url: str | None, model: str
) -> tuple[ProviderDefinition, str, str]:
    provider = PROVIDERS.get(provider_code)
    if provider is None:
        raise ProviderConfigError("不支持的模型服务商")
    resolved_url = _validate_url(base_url or provider.default_base_url, allow_empty=False)
    resolved_model = model.strip()
    if not resolved_model or len(resolved_model) > 160:
        raise ProviderConfigError("模型名称不能为空，且不能超过 160 个字符")
    return provider, resolved_url, resolved_model


def mask_api_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * min(12, len(value) - 8)}{value[-4:]}"


def list_provider_configs(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT provider_code, display_name, base_url, default_model, enabled,
                      api_key_encrypted IS NOT NULL AS has_api_key, updated_at, last_test_at,
                      last_test_status, last_test_message
               FROM llm_provider_configs ORDER BY updated_at DESC, provider_code"""
        )
        rows = cur.fetchall()
    return [
        {
            "providerCode": row[0],
            "displayName": row[1],
            "baseUrl": row[2],
            "defaultModel": row[3],
            "enabled": row[4],
            "hasApiKey": row[5],
            "updatedAt": row[6].isoformat() if row[6] else None,
            "lastTestAt": row[7].isoformat() if row[7] else None,
            "lastTestStatus": row[8],
            "lastTestMessage": row[9],
        }
        for row in rows
    ]


def list_agent_model_bindings(conn: Any) -> list[dict[str, Any]]:
    """Return the narrow allow-list of agents that may opt into a model call."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT b.agent_code, b.provider_code, b.enabled, b.updated_at,
                      p.display_name, p.default_model, p.enabled, p.last_test_status
               FROM llm_agent_bindings b
               JOIN llm_provider_configs p ON p.provider_code = b.provider_code
               ORDER BY b.agent_code"""
        )
        saved = {row[0]: row for row in cur.fetchall()}
    return [
        {
            "agentCode": code,
            "agentName": name,
            "providerCode": row[1] if row else None,
            "providerName": row[4] if row else None,
            "model": row[5] if row else None,
            "enabled": bool(row[2]) if row else False,
            "providerEnabled": bool(row[6]) if row else False,
            "providerTestStatus": row[7] if row else None,
            "updatedAt": row[3].isoformat() if row else None,
        }
        for code, name in AGENT_MODEL_OPTIONS.items()
        for row in [saved.get(code)]
    ]


def save_agent_model_binding(conn: Any, agent_code: str, provider_code: str, enabled: bool) -> dict[str, Any]:
    if agent_code not in AGENT_MODEL_OPTIONS:
        raise ProviderConfigError("该智能代理不允许配置外部模型")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT provider_code, enabled, api_key_encrypted IS NOT NULL, last_test_status
               FROM llm_provider_configs WHERE provider_code = %s""",
            (provider_code,),
        )
        provider = cur.fetchone()
        if not provider:
            raise ProviderConfigError("请先保存模型服务商配置")
        if enabled and (not provider[1] or not provider[2] or provider[3] != "passed"):
            raise ProviderConfigError("请先启用服务商并通过连通性测试，再启用智能代理")
        cur.execute(
            """INSERT INTO llm_agent_bindings (agent_code, provider_code, enabled, updated_at)
               VALUES (%s, %s, %s, NOW())
               ON CONFLICT (agent_code) DO UPDATE SET provider_code = EXCLUDED.provider_code,
                 enabled = EXCLUDED.enabled, updated_at = NOW()""",
            (agent_code, provider_code, enabled),
        )
    conn.commit()
    return next(item for item in list_agent_model_bindings(conn) if item["agentCode"] == agent_code)


def get_agent_model_binding(conn: Any, agent_code: str) -> dict[str, Any] | None:
    """Load the secret-bearing record only at the model invocation boundary."""
    if agent_code not in AGENT_MODEL_OPTIONS:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """SELECT b.agent_code, b.provider_code, b.enabled, p.base_url, p.default_model,
                      p.api_key_encrypted, p.enabled, p.last_test_status
               FROM llm_agent_bindings b
               JOIN llm_provider_configs p ON p.provider_code = b.provider_code
               WHERE b.agent_code = %s""",
            (agent_code,),
        )
        row = cur.fetchone()
    if not row or not row[6]:
        return None
    provider = PROVIDERS.get(row[1])
    if provider is None:
        return None
    return {
        "agent_code": row[0], "provider_code": row[1], "enabled": row[2],
        "base_url": row[3], "default_model": row[4], "api_key_encrypted": row[5],
        "protocol": provider.protocol, "last_test_status": row[7],
    }


def save_provider_config(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    provider, base_url, model = validate_provider_input(
        str(payload.get("providerCode", "")),
        payload.get("baseUrl"),
        str(payload.get("defaultModel", "")),
    )
    api_key = str(payload.get("apiKey", "")).strip()
    # The UI intentionally never reads an existing key back.  A blank value on
    # an update therefore means "keep the encrypted key", not "delete it".
    with conn.cursor() as cur:
        cur.execute(
            """SELECT base_url, default_model, api_key_encrypted IS NOT NULL
               FROM llm_provider_configs WHERE provider_code = %s""",
            (provider.code,),
        )
        saved: tuple[Any, ...] | None = cur.fetchone()
    if provider.requires_api_key and not api_key and not (saved and saved[2]):
        raise ProviderConfigError("请填写 API 密钥")
    encrypted = _cipher().encrypt(api_key.encode("utf-8")).decode("utf-8") if api_key else None
    connection_changed = bool(
        saved and (saved[0] != base_url or saved[1] != model or encrypted is not None)
    )
    display_name = str(payload.get("displayName") or provider.name).strip()[:80] or provider.name
    enabled = bool(payload.get("enabled", True))
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO llm_provider_configs
                 (provider_code, display_name, base_url, default_model, enabled, api_key_encrypted, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, NOW())
               ON CONFLICT (provider_code) DO UPDATE SET
                 display_name = EXCLUDED.display_name, base_url = EXCLUDED.base_url,
                 default_model = EXCLUDED.default_model, enabled = EXCLUDED.enabled,
                 api_key_encrypted = CASE WHEN EXCLUDED.api_key_encrypted IS NULL
                                          THEN llm_provider_configs.api_key_encrypted
                                          ELSE EXCLUDED.api_key_encrypted END,
                 last_test_at = CASE WHEN %s THEN NULL ELSE llm_provider_configs.last_test_at END,
                 last_test_status = CASE WHEN %s THEN NULL ELSE llm_provider_configs.last_test_status END,
                 last_test_message = CASE WHEN %s THEN NULL ELSE llm_provider_configs.last_test_message END,
                 updated_at = NOW()
               RETURNING provider_code, display_name, base_url, default_model, enabled,
                         api_key_encrypted IS NOT NULL, updated_at, last_test_at,
                         last_test_status, last_test_message""",
            (provider.code, display_name, base_url, model, enabled, encrypted,
             connection_changed, connection_changed, connection_changed),
        )
        row = cur.fetchone()
    conn.commit()
    return {
        "providerCode": row[0],
        "displayName": row[1],
        "baseUrl": row[2],
        "defaultModel": row[3],
        "enabled": row[4],
        "hasApiKey": row[5],
        "updatedAt": row[6].isoformat() if row[6] else None,
        "lastTestAt": row[7].isoformat() if row[7] else None,
        "lastTestStatus": row[8],
        "lastTestMessage": row[9],
    }


def _decrypt_key(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _cipher().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ProviderConfigError("已保存的 API 密钥无法解密，请重新保存") from exc


def test_provider_config(conn: Any, provider_code: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT provider_code, base_url, default_model, api_key_encrypted FROM llm_provider_configs WHERE provider_code = %s",
            (provider_code,),
        )
        row = cur.fetchone()
    if not row:
        raise ProviderConfigError("请先保存该服务商配置")
    provider, base_url, model = validate_provider_input(row[0], row[1], row[2])
    api_key = _decrypt_key(row[3])
    if provider.requires_api_key and not api_key:
        raise ProviderConfigError("该服务商缺少 API 密钥")
    status, message = _probe_provider(provider, base_url, model, api_key)
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE llm_provider_configs
               SET last_test_at = %s, last_test_status = %s, last_test_message = %s
               WHERE provider_code = %s""",
            (now, status, message[:500], provider_code),
        )
    conn.commit()
    return {
        "providerCode": provider_code,
        "status": status,
        "message": message,
        "testedAt": now.isoformat(),
    }


def _probe_provider(
    provider: ProviderDefinition, base_url: str, model: str, api_key: str | None
) -> tuple[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            if provider.protocol == "gemini":
                response = client.get(f"{base_url}/models", params={"key": api_key})
            elif provider.protocol == "ollama":
                response = client.get(f"{base_url}/api/tags")
            elif provider.protocol == "anthropic":
                response = client.get(
                    f"{base_url}/models", headers={**headers, "anthropic-version": "2023-06-01"}
                )
            else:
                response = client.get(f"{base_url}/models", headers=headers)
    except httpx.HTTPError as exc:
        return "failed", f"连接失败：{exc.__class__.__name__}"
    if 200 <= response.status_code < 300:
        return "passed", "连通正常，已完成只读服务探测"
    if response.status_code in {401, 403}:
        return "failed", "鉴权失败，请检查 API 密钥或服务商权限"
    return "failed", f"服务返回 HTTP {response.status_code}"


def provider_catalog() -> list[dict[str, Any]]:
    return [
        {
            "providerCode": item.code,
            "displayName": item.name,
            "protocol": item.protocol,
            "defaultBaseUrl": item.default_base_url,
            "defaultModel": item.default_model,
            "recommendedModels": item.recommended_models,
            "capabilities": item.capabilities,
            "documentationUrl": item.documentation_url,
            "requiresApiKey": item.requires_api_key,
        }
        for item in PROVIDERS.values()
    ]
