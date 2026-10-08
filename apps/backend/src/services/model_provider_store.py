"""Encrypted persistence and safe connectivity checks for language-model providers."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import psycopg2
from cryptography.fernet import Fernet, InvalidToken

from apps.backend.src.services.pi_bridge import PiBridgeError, call_bridge, pi_catalog, pi_provider


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
        "claude-sonnet-4-6",
        ("claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"),
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
    "xiaomi": ProviderDefinition(
        "xiaomi",
        "小米 MiMo",
        "openai",
        "https://api.xiaomimimo.com/v1",
        "mimo-v2.5-pro",
        ("mimo-v2.5-pro", "mimo-v2.5"),
        ("analysis", "coding", "vision"),
        "https://mimo.mi.com/docs/quick-start/summary/model",
    ),
    "openrouter": ProviderDefinition(
        "openrouter",
        "OpenRouter",
        "openai",
        "https://openrouter.ai/api/v1",
        "openai/gpt-5.2",
        ("openai/gpt-5.2", "anthropic/claude-opus-4.6", "google/gemini-3.6-flash"),
        ("analysis", "coding", "vision"),
        "https://openrouter.ai/docs/quickstart",
    ),
    "siliconflow": ProviderDefinition(
        "siliconflow",
        "硅基流动",
        "openai",
        "https://api.siliconflow.com/v1",
        "deepseek-ai/DeepSeek-V3",
        ("deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "Qwen/Qwen3-32B"),
        ("analysis", "coding"),
        "https://docs.siliconflow.cn/cn/api-reference/chat-completions/chat-completions",
    ),
    "zhipu": ProviderDefinition(
        "zhipu",
        "智谱 AI（GLM）",
        "openai",
        "https://api.z.ai/api/paas/v4",
        "glm-5.2",
        ("glm-5.2", "glm-5.1", "glm-5", "glm-4.7"),
        ("analysis", "coding"),
        "https://docs.z.ai/guides/llm/glm-5.2",
    ),
    "moonshot": ProviderDefinition(
        "moonshot",
        "Moonshot AI（月之暗面）",
        "openai",
        "https://api.moonshot.ai/v1",
        "kimi-k3",
        ("kimi-k3", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6"),
        ("analysis", "coding", "vision"),
        "https://platform.kimi.ai/docs/overview",
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
        "perplexity",
        "https://api.perplexity.ai",
        "sonar-pro",
        ("sonar", "sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"),
        ("analysis",),
        "https://docs.perplexity.ai/docs/sonar/openai-compatibility",
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
        "openai_compatible",
        "自定义 OpenAI 兼容服务",
        "openai",
        "",
        "",
        (),
        ("analysis", "coding"),
        "https://platform.openai.com/docs/api-reference/chat",
    ),
}

AGENT_MODEL_OPTIONS: dict[str, str] = {
    "orchestrator_agent": "任务编排 Agent",
    "review_agent": "复盘 Agent",
    "doc_agent": "文档 Agent",
    "pre_match_interpretation_agent": "赛前解读 Agent",
    "post_match_report_agent": "自动赛后报告 Agent",
    "news_extraction_agent": "新闻事件提取 Agent",
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
    provider = provider_definition(provider_code)
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
    # Never expose key prefixes, suffixes, length, or encrypted ciphertext to
    # the browser.  The fixed mask only indicates that a usable secret exists.
    return "••••••••••••"


PI_ALIASES = {"gemini": "google", "zhipu": "zai", "moonshot": "moonshotai"}
LEGACY_APIS = {
    "openai": "openai-completions",
    "perplexity": "openai-completions",
    "ollama": "openai-completions",
    "anthropic": "anthropic-messages",
    "gemini": "google-generative-ai",
}
CUSTOM_APIS = set(LEGACY_APIS.values()) | {"openai-responses", "auto"}
CONFIG_COLUMNS = "provider_code, display_name, base_url, default_model, enabled, api_key_encrypted, updated_at, last_test_at, last_test_status, last_test_message, auth_type, api_protocol, pi_credential_encrypted"


def pi_id(code: str) -> str:
    return PI_ALIASES.get(code, code)


def provider_definition(code: str) -> ProviderDefinition | None:
    if code in PROVIDERS:
        return PROVIDERS[code]
    item = pi_provider(pi_id(code))
    if not item or not item["models"]:
        return None
    model = item["models"][0]
    return ProviderDefinition(
        code,
        item["name"],
        model["api"],
        item["baseUrl"] or model["baseUrl"],
        model["id"],
        tuple(m["id"] for m in item["models"][:8]),
        ("analysis",),
        "https://pi.dev/models",
    )


def _requires_api_key(provider_code: str) -> bool:
    provider = provider_definition(provider_code)
    return provider.requires_api_key if provider else True


def _config_record(row: Any) -> dict[str, Any]:
    return dict(zip(CONFIG_COLUMNS.replace(" ", "").split(","), row, strict=True))


def _public_config(record: dict[str, Any]) -> dict[str, Any]:
    has_key = bool(record["api_key_encrypted"])
    auth_type = record["auth_type"]
    connected = (
        bool(record["pi_credential_encrypted"])
        if auth_type == "oauth"
        else has_key or auth_type == "none"
    )
    return {
        "providerCode": record["provider_code"],
        "displayName": record["display_name"],
        "baseUrl": record["base_url"],
        "defaultModel": record["default_model"],
        "enabled": record["enabled"],
        "hasApiKey": has_key,
        "apiKeyMask": mask_api_key(record["api_key_encrypted"]),
        "updatedAt": record["updated_at"].isoformat() if record["updated_at"] else None,
        "lastTestAt": record["last_test_at"].isoformat() if record["last_test_at"] else None,
        "lastTestStatus": record["last_test_status"],
        "lastTestMessage": record["last_test_message"],
        "requiresApiKey": auth_type == "api_key",
        "authType": auth_type,
        "hasCredential": connected,
        "apiProtocol": record["api_protocol"],
    }


def list_provider_configs(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {CONFIG_COLUMNS} FROM llm_provider_configs ORDER BY updated_at DESC, provider_code"
        )
        return [_public_config(_config_record(row)) for row in cur.fetchall()]


def list_agent_model_bindings(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""SELECT b.agent_code, b.provider_code, b.enabled, b.updated_at,
                      p.display_name, p.default_model, p.enabled, p.last_test_status
               FROM llm_agent_bindings b JOIN llm_provider_configs p ON p.provider_code = b.provider_code
               ORDER BY b.agent_code""")
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


def save_agent_model_binding(
    conn: Any, agent_code: str, provider_code: str, enabled: bool
) -> dict[str, Any]:
    if agent_code not in AGENT_MODEL_OPTIONS:
        raise ProviderConfigError("该智能代理不允许配置外部模型")
    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '5s'", ())
        cur.execute(
            """SELECT provider_code, enabled,
                   CASE WHEN auth_type = 'oauth' THEN pi_credential_encrypted IS NOT NULL
                        WHEN auth_type = 'none' THEN true ELSE api_key_encrypted IS NOT NULL END,
                   last_test_status FROM llm_provider_configs WHERE provider_code = %s FOR UPDATE""",
            (provider_code,),
        )
        provider = cur.fetchone()
        if not provider:
            raise ProviderConfigError("请先保存模型服务商配置")
        if enabled and not provider[2]:
            raise ProviderConfigError("请先保存服务商 API 密钥或完成账号登录，再启用智能代理")
        if enabled and provider[3] != "passed":
            raise ProviderConfigError("请先通过服务商连通性测试，再启用智能代理")
        if enabled and not provider[1]:
            raise ProviderConfigError("服务商已通过测试但尚未启用，请先在模型接入中开启服务商")
        cur.execute(
            """INSERT INTO llm_agent_bindings (agent_code, provider_code, enabled, updated_at)
                   VALUES (%s, %s, %s, NOW()) ON CONFLICT (agent_code) DO UPDATE SET
                   provider_code = EXCLUDED.provider_code, enabled = EXCLUDED.enabled, updated_at = NOW()""",
            (agent_code, provider_code, enabled),
        )
    conn.commit()
    return next(item for item in list_agent_model_bindings(conn) if item["agentCode"] == agent_code)


def get_agent_model_binding(conn: Any, agent_code: str) -> dict[str, Any] | None:
    if agent_code not in AGENT_MODEL_OPTIONS:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """SELECT b.agent_code, b.provider_code, b.enabled, p.base_url, p.default_model,
                   p.api_key_encrypted, p.enabled, p.last_test_status FROM llm_agent_bindings b
                   JOIN llm_provider_configs p ON p.provider_code = b.provider_code WHERE b.agent_code = %s""",
            (agent_code,),
        )
        row = cur.fetchone()
    if not row or not row[6]:
        return None
    return {
        "agent_code": row[0],
        "provider_code": row[1],
        "enabled": row[2],
        "base_url": row[3],
        "default_model": row[4],
        "api_key_encrypted": row[5],
        "last_test_status": row[7],
    }


def _decrypt_key(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ProviderConfigError("已保存的凭据无法解密，请重新保存或登录") from exc


def _encrypted_credential(value: dict[str, Any]) -> str:
    return _cipher().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()


def _credential(record: dict[str, Any]) -> dict[str, Any] | None:
    raw = _decrypt_key(record["pi_credential_encrypted"])
    try:
        credential = json.loads(raw) if raw else None
        if credential is not None and not isinstance(credential, dict):
            raise ValueError("Invalid credential")
    except ValueError as exc:
        raise ProviderConfigError("已保存的凭据格式无效，请重新保存或登录") from exc
    if record["auth_type"] == "oauth":
        if not credential or credential.get("type") != "oauth":
            raise ProviderConfigError("请先完成账号登录")
        return credential
    if record["auth_type"] == "none":
        return None
    key = _decrypt_key(record["api_key_encrypted"])
    if not key:
        raise ProviderConfigError("请填写 API 密钥")
    return {"type": "api_key", "key": key, "env": (credential or {}).get("env", {})}


def save_provider_config(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    provider, base_url, model = validate_provider_input(
        str(payload.get("providerCode", "")),
        payload.get("baseUrl"),
        str(payload.get("defaultModel", "")),
    )
    api_key = str(payload.get("apiKey") or "").strip()
    if api_key == mask_api_key("saved"):
        raise ProviderConfigError("请填写真实 API 密钥，不能提交掩码")
    api = payload.get("apiProtocol") or None
    if api and api not in CUSTOM_APIS:
        raise ProviderConfigError("不支持的兼容接口类型")
    auth_type = payload.get("authType") or ("api_key" if provider.requires_api_key else "none")
    if auth_type not in {"api_key", "oauth", "none"}:
        raise ProviderConfigError("不支持的认证方式")
    if auth_type == "none" and provider.code not in {"ollama", "openai_compatible"}:
        raise ProviderConfigError("该服务商需要凭据")
    item = pi_provider(pi_id(provider.code))
    if auth_type == "api_key" and item and "api_key" not in item["authMethods"]:
        raise ProviderConfigError("该服务商需要账号登录，不支持 API Key 接入")
    if auth_type == "oauth" and (not item or "oauth" not in item["authMethods"]):
        raise ProviderConfigError("该服务商不支持账号登录")
    env = payload.get("providerEnv")
    if env is not None and (
        not isinstance(env, dict)
        or len(env) > 12
        or any(
            not isinstance(k, str)
            or not k.replace("_", "").isalnum()
            or not k.isupper()
            or not isinstance(v, str)
            or len(v) > 4096
            for k, v in env.items()
        )
    ):
        raise ProviderConfigError("附加配置必须是最多 12 项的环境变量名称与文本值")
    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '5s'", ())
        cur.execute(
            f"SELECT {CONFIG_COLUMNS} FROM llm_provider_configs WHERE provider_code = %s FOR UPDATE",
            (provider.code,),
        )
        row = cur.fetchone()
    saved = _config_record(row) if row else None
    if auth_type == "api_key" and not api_key and not (saved and saved["api_key_encrypted"]):
        raise ProviderConfigError("请填写 API 密钥")
    if auth_type == "oauth" and not (
        saved and saved["auth_type"] == "oauth" and saved["pi_credential_encrypted"]
    ):
        raise ProviderConfigError("请先完成账号登录")
    encrypted = _cipher().encrypt(api_key.encode()).decode() if api_key else None
    credential_encrypted = saved["pi_credential_encrypted"] if saved else None
    if auth_type == "api_key" and (
        api_key or env is not None or saved and saved["auth_type"] != auth_type
    ):
        key = api_key or _decrypt_key(saved["api_key_encrypted"] if saved else None)
        existing = _credential(saved) if saved and saved["auth_type"] == "api_key" else None
        credential_encrypted = _encrypted_credential(
            {
                "type": "api_key",
                "key": key,
                "env": env if env is not None else (existing or {}).get("env", {}),
            }
        )
    if auth_type == "none":
        credential_encrypted = None
    # Existing connections retain their wire protocol until explicitly changed.
    resolved_api = api or (saved["api_protocol"] if saved else "auto")
    changed = bool(
        saved
        and (
            saved["base_url"] != base_url
            or saved["default_model"] != model
            or encrypted
            or credential_encrypted != saved["pi_credential_encrypted"]
            or saved["auth_type"] != auth_type
            or saved["api_protocol"] != resolved_api
        )
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO llm_provider_configs (provider_code, display_name, base_url, default_model, enabled, api_key_encrypted, auth_type, api_protocol, pi_credential_encrypted, updated_at)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                  ON CONFLICT (provider_code) DO UPDATE SET display_name = EXCLUDED.display_name,
                  base_url = EXCLUDED.base_url, default_model = EXCLUDED.default_model, enabled = EXCLUDED.enabled,
                  api_key_encrypted = COALESCE(EXCLUDED.api_key_encrypted, llm_provider_configs.api_key_encrypted),
                  auth_type = EXCLUDED.auth_type, api_protocol = EXCLUDED.api_protocol,
                  pi_credential_encrypted = EXCLUDED.pi_credential_encrypted,
                  last_test_at = CASE WHEN %s THEN NULL ELSE llm_provider_configs.last_test_at END,
                  last_test_status = CASE WHEN %s THEN NULL ELSE llm_provider_configs.last_test_status END,
                  last_test_message = CASE WHEN %s THEN NULL ELSE llm_provider_configs.last_test_message END,
                  updated_at = NOW() RETURNING {CONFIG_COLUMNS}""",
            (
                provider.code,
                str(payload.get("displayName") or provider.name)[:80],
                base_url,
                model,
                bool(payload.get("enabled", True)),
                encrypted,
                auth_type,
                resolved_api,
                credential_encrypted,
                changed,
                changed,
                changed,
            ),
        )
        result = _public_config(_config_record(cur.fetchone()))
    conn.commit()
    return result


def _pi_failure(result: dict[str, Any]) -> PiBridgeError:
    code = result.get("code") or "MODEL_CALL_FAILED"
    status = result.get("status")
    if status in {401, 403}:
        code = "MODEL_AUTH_FAILED"
    elif status == 404:
        code = "MODEL_NOT_FOUND"
    elif status == 429:
        code = "MODEL_RATE_LIMITED"
    elif status and status >= 500:
        code = "MODEL_PROVIDER_UNAVAILABLE"
    messages = {
        "MODEL_AUTH_FAILED": "模型鉴权失败，请检查 API 密钥或重新登录",
        "MODEL_TIMEOUT": "模型调用超时，请稍后重试",
        "MODEL_NOT_FOUND": "所选模型或服务地址不存在",
        "MODEL_RATE_LIMITED": "服务商限额或频率受限，请稍后重试",
        "MODEL_EMPTY_RESPONSE": "模型未返回可用文本",
        "MODEL_PROVIDER_UNAVAILABLE": "模型服务商暂时不可用，请稍后重试",
    }
    return PiBridgeError(messages.get(code, "Pi 模型调用失败，请检查配置或重新登录"), code)


_credential_connections = threading.BoundedSemaphore(4)


@contextmanager
def provider_connection(caller: Any):
    """Credential rotation must never commit a caller's pending business writes."""
    if not _credential_connections.acquire(timeout=1):
        raise PiBridgeError("模型调用繁忙，请稍后重试", "MODEL_RATE_LIMITED")
    connection = None
    try:
        # A bounded independent connection also avoids nested application-pool starvation.
        connection = psycopg2.connect(caller.dsn, connect_timeout=5)
        yield connection
    except psycopg2.Error as exc:
        raise PiBridgeError("模型凭据读取或更新暂时受限，请稍后重试", "MODEL_CONFIG_ERROR") from exc
    finally:
        if connection is not None:
            connection.close()
        _credential_connections.release()


def invoke_provider(
    conn: Any,
    provider_code: str,
    prompt: str,
    system: str,
    *,
    max_tokens: int = 800,
    timeout: float = 30,
    require_ready: bool = True,
    agent_code: str | None = None,
) -> dict[str, Any]:
    # The provider row serializes credential refresh across threads/processes.
    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '5s'")
        cur.execute(
            f"SELECT {CONFIG_COLUMNS} FROM llm_provider_configs WHERE provider_code = %s FOR UPDATE",
            (provider_code,),
        )
        row = cur.fetchone()
        if not row:
            raise ProviderConfigError("请先保存服务商配置")
        record = _config_record(row)
        if agent_code:
            cur.execute(
                "SELECT provider_code, enabled FROM llm_agent_bindings WHERE agent_code = %s FOR SHARE",
                (agent_code,),
            )
            binding = cur.fetchone()
            if not binding or binding[0] != provider_code or not binding[1]:
                raise ProviderConfigError("代理绑定已变化或停用，请重新选择")
        if require_ready and (not record["enabled"] or record["last_test_status"] != "passed"):
            raise ProviderConfigError("请启用服务商并重新验证模型")
        definition = provider_definition(provider_code)
        if not definition:
            raise ProviderConfigError("不支持的模型服务商")
        api = (
            None
            if record["api_protocol"] == "auto"
            else record["api_protocol"] or LEGACY_APIS.get(definition.protocol)
        )
        base_url = record["base_url"]
        if definition.protocol == "ollama" and api in {None, "openai-completions"}:
            base_url = base_url.removesuffix("/v1") + "/v1"
        result = call_bridge(
            {
                "operation": "complete",
                "providerId": pi_id(provider_code),
                "credential": _credential(record),
                "model": record["default_model"],
                "baseUrl": base_url,
                "api": api,
                "keyless": record["auth_type"] == "none",
                "prompt": prompt,
                "system": system,
                "maxTokens": max_tokens,
                "timeoutMs": round(timeout * 1000),
            },
            timeout=timeout + 5,
        )
        credential = result.pop("credential", None)
        if credential and record["auth_type"] == "oauth":
            cur.execute(
                "UPDATE llm_provider_configs SET pi_credential_encrypted = %s WHERE provider_code = %s",
                (_encrypted_credential(credential), provider_code),
            )
    # Persist rotated refresh tokens even if the subsequent completion failed.
    conn.commit()
    result["version"] = record["updated_at"]
    if result.get("ok") is not True:
        raise _pi_failure(result)
    return result


def test_provider_config(conn: Any, provider_code: str) -> dict[str, Any]:
    try:
        result = invoke_provider(
            conn,
            provider_code,
            "只回复 OK",
            "这是模型接入连通性测试，不执行任何业务操作。",
            max_tokens=64,
            timeout=20,
            require_ready=False,
        )
        status, message = "passed", "Pi 调用正常，已验证所选模型可生成响应"
        version = result["version"]
    except PiBridgeError as exc:
        status, message, version = "failed", str(exc), None
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        # Never mark a concurrently changed configuration as verified.
        cur.execute(
            """UPDATE llm_provider_configs SET last_test_at = %s, last_test_status = %s, last_test_message = %s
                   WHERE provider_code = %s AND (%s IS NULL OR updated_at = %s)""",
            (now, status, message, provider_code, version, version),
        )
        if cur.rowcount == 0:
            raise ProviderConfigError("配置在验证期间已变化，请重新验证")
    conn.commit()
    return {
        "providerCode": provider_code,
        "status": status,
        "message": message,
        "testedAt": now.isoformat(),
    }


def provider_catalog() -> list[dict[str, Any]]:
    presets = {item.code: item for item in PROVIDERS.values()}
    for item in pi_catalog():
        code = next(
            (alias for alias, target in PI_ALIASES.items() if target == item["id"]), item["id"]
        )
        definition = provider_definition(code)
        if definition and item["models"]:
            presets[code] = definition
    result = []
    for preset in presets.values():
        pi = pi_provider(pi_id(preset.code))
        models = pi["models"] if pi else []
        result.append(
            {
                "providerCode": preset.code,
                "displayName": preset.name,
                "protocol": preset.protocol,
                "defaultBaseUrl": (pi["baseUrl"] if pi else None)
                or (
                    preset.default_base_url + "/v1"
                    if preset.code == "ollama"
                    else preset.default_base_url
                ),
                "defaultModel": next(
                    (m["id"] for m in models if m["id"] == preset.default_model),
                    models[0]["id"] if models else preset.default_model,
                ),
                "recommendedModels": [m["id"] for m in models[:8]]
                if models
                else list(preset.recommended_models),
                "capabilities": preset.capabilities,
                "documentationUrl": preset.documentation_url,
                "requiresApiKey": preset.requires_api_key,
                "authMethods": pi["authMethods"]
                if pi
                else (
                    ["api_key", "none"]
                    if preset.code == "openai_compatible"
                    else ["api_key"]
                    if preset.requires_api_key
                    else ["none"]
                ),
                "oauthLabel": pi["oauthLabel"] if pi else None,
                "modelCount": len(models),
                "engine": "pi-ai",
            }
        )
    return result


def provider_models(
    provider_code: str, query: str = "", limit: int = 100, offset: int = 0
) -> dict[str, Any]:
    definition = provider_definition(provider_code)
    if not definition:
        raise ProviderConfigError("不支持的模型服务商")
    item = pi_provider(pi_id(provider_code))
    models: list[dict[str, Any]] = (
        item["models"]
        if item
        else [
            {
                "id": model,
                "name": model,
                "input": ["text"],
                "reasoning": False,
                "api": LEGACY_APIS.get(definition.protocol),
                "contextWindow": None,
                "maxTokens": None,
            }
            for model in definition.recommended_models
        ]
    )
    found = [m for m in models if query.casefold() in (m["id"] + " " + m["name"]).casefold()]
    return {"models": found[offset : offset + limit], "total": len(found), "engine": "pi-ai"}
