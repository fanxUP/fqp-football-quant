from __future__ import annotations

import pytest

from apps.backend.src.services.model_agent_prompts import get_agent_system_instruction
from apps.backend.src.services.model_gateway import _request_completion


class FakeClient:
    def __init__(self) -> None:
        self.args = ()
        self.kwargs = {}
        self.response = object()

    def post(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        return self.response


def _binding(protocol: str) -> dict[str, str]:
    return {"protocol": protocol, "base_url": "https://provider.example/v1", "default_model": "test-model"}


def test_agent_instruction_is_fixed_and_unknown_agent_is_rejected() -> None:
    instruction = get_agent_system_instruction("review_agent")

    assert "不得假装具备执行命令" in instruction
    with pytest.raises(ValueError, match="没有可调用"):
        get_agent_system_instruction("prediction_agent")


@pytest.mark.parametrize("protocol", ["openai", "ollama"])
def test_openai_compatible_payload_includes_system_boundary(protocol: str) -> None:
    client = FakeClient()
    response = _request_completion(client, _binding(protocol), "key", "用户任务", "固定边界")

    assert response is client.response
    assert client.kwargs["json"]["messages"] == [
        {"role": "system", "content": "固定边界"}, {"role": "user", "content": "用户任务"},
    ]


@pytest.mark.parametrize("protocol", ["anthropic", "gemini"])
def test_provider_specific_payload_includes_system_boundary(protocol: str) -> None:
    client = FakeClient()
    _request_completion(client, _binding(protocol), "key", "用户任务", "固定边界")

    payload = client.kwargs["json"]
    if protocol == "anthropic":
        assert payload["system"] == "固定边界"
    else:
        assert payload["systemInstruction"]["parts"][0]["text"] == "固定边界"
