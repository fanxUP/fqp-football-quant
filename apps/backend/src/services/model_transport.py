"""Provider-protocol HTTP transport shared by connection tests and Agent calls."""

from __future__ import annotations

from typing import Any

import httpx


def request_completion(
    client: Any,
    binding: dict[str, Any],
    api_key: str | None,
    prompt: str,
    system_instruction: str,
    *,
    max_tokens: int = 800,
) -> httpx.Response:
    protocol = str(binding["protocol"])
    base_url = str(binding["base_url"])
    model = str(binding["default_model"])
    if protocol == "gemini":
        return client.post(
            f"{base_url}/models/{model}:generateContent",
            params={"key": api_key},
            json={
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens},
            },
        )
    if protocol == "anthropic":
        return client.post(
            f"{base_url}/messages",
            headers={"x-api-key": api_key or "", "anthropic-version": "2023-06-01"},
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": system_instruction,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    if protocol == "ollama":
        return client.post(
            f"{base_url}/api/chat",
            headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
        )
    return client.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "max_tokens": max_tokens,
        },
    )


def read_completion_content(protocol: str, payload: dict[str, Any]) -> str:
    if protocol == "gemini":
        return str(payload["candidates"][0]["content"]["parts"][0]["text"]).strip()
    if protocol == "anthropic":
        return str(payload["content"][0]["text"]).strip()
    if protocol == "ollama":
        return str(payload["message"]["content"]).strip()
    return str(payload["choices"][0]["message"]["content"]).strip()
