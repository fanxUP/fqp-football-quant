"""Single safe invocation boundary for opt-in internal model agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from apps.backend.src.services.model_agent_prompts import get_agent_system_instruction
from apps.backend.src.services.model_provider_store import (
    _decrypt_key,
    get_agent_model_binding,
)


class ModelGatewayError(RuntimeError):
    """A configured model cannot safely serve the requested agent call."""


@dataclass(frozen=True)
class ModelReply:
    provider_code: str
    model: str
    content: str


def invoke_agent_model(conn: Any, agent_code: str, prompt: str) -> ModelReply:
    """Invoke one explicitly enabled binding. Scheduled betting logic never calls this."""
    if not prompt.strip() or len(prompt) > 8_000:
        raise ModelGatewayError("请求内容不能为空，且不能超过 8000 个字符")
    binding = get_agent_model_binding(conn, agent_code)
    if not binding or not binding["enabled"]:
        raise ModelGatewayError("该智能代理未启用模型调用")
    if binding["last_test_status"] != "passed":
        raise ModelGatewayError("模型服务商配置变更后，请重新测试连接再试运行")
    api_key = _decrypt_key(binding["api_key_encrypted"])
    try:
        system_instruction = get_agent_system_instruction(agent_code)
    except ValueError as exc:
        raise ModelGatewayError(str(exc)) from exc
    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            response = _request_completion(client, binding, api_key, prompt, system_instruction)
            response.raise_for_status()
            content = _read_content(binding["protocol"], response.json())
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        raise ModelGatewayError("模型调用失败，请检查服务商、模型名称与额度") from exc
    if not content:
        raise ModelGatewayError("模型未返回可用文本")
    return ModelReply(binding["provider_code"], binding["default_model"], content[:12_000])


def _request_completion(
    client: httpx.Client,
    binding: dict[str, Any],
    api_key: str | None,
    prompt: str,
    system_instruction: str,
) -> httpx.Response:
    protocol, base_url, model = binding["protocol"], binding["base_url"], binding["default_model"]
    if protocol == "gemini":
        return client.post(
            f"{base_url}/models/{model}:generateContent", params={"key": api_key},
            json={"systemInstruction": {"parts": [{"text": system_instruction}]}, "contents": [{"parts": [{"text": prompt}]}]},
        )
    if protocol == "anthropic":
        return client.post(
            f"{base_url}/messages", headers={"x-api-key": api_key or "", "anthropic-version": "2023-06-01"},
            json={"model": model, "max_tokens": 800, "system": system_instruction, "messages": [{"role": "user", "content": prompt}]},
        )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    endpoint = "/api/chat" if protocol == "ollama" else "/chat/completions"
    return client.post(
        f"{base_url}{endpoint}", headers=headers,
        json={"model": model, "messages": [{"role": "system", "content": system_instruction}, {"role": "user", "content": prompt}], "stream": False, "max_tokens": 800},
    )


def _read_content(protocol: str, payload: dict[str, Any]) -> str:
    if protocol == "gemini":
        return str(payload["candidates"][0]["content"]["parts"][0]["text"]).strip()
    if protocol == "anthropic":
        return str(payload["content"][0]["text"]).strip()
    if protocol == "ollama":
        return str(payload["message"]["content"]).strip()
    return str(payload["choices"][0]["message"]["content"]).strip()
