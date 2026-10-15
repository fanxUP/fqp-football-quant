from __future__ import annotations

import pytest

from apps.backend.src.services.model_agent_prompts import get_agent_system_instruction
from apps.backend.src.services.model_gateway import (
    ModelGatewayError,
    invoke_agent_model,
)


def test_agent_instruction_is_fixed_and_unknown_agent_is_rejected() -> None:
    instruction = get_agent_system_instruction("review_agent")

    assert "不得假装具备执行命令" in instruction
    with pytest.raises(ValueError, match="没有可调用"):
        get_agent_system_instruction("prediction_agent")


def test_news_extraction_agent_cannot_issue_predictions_or_bets() -> None:
    instruction = get_agent_system_instruction("news_extraction_agent")

    assert "不得预测胜平负" in instruction
    assert "不得" in instruction and "投注" in instruction


def test_invocation_requires_a_fresh_provider_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.backend.src.services.model_gateway.get_agent_model_binding",
        lambda _conn, _agent_code: {"enabled": True, "last_test_status": None},
    )

    with pytest.raises(ModelGatewayError, match="重新测试连接"):
        invoke_agent_model(object(), "review_agent", "检查数据质量")
