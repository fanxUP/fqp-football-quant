from __future__ import annotations

import pytest

from apps.backend.src.services.agent_interpretation import (
    InterpretationSourceError,
    build_interpretation_prompt,
)


def test_pre_match_prompt_preserves_server_snapshot_and_optional_question() -> None:
    prompt = build_interpretation_prompt(
        source_type="pre_match", title="赛前解读：周日001", snapshot={"官方比赛": {"编号": "周日001"}},
        focus_question="为什么信号冲突？",
    )

    assert "官方比赛" in prompt
    assert "为什么信号冲突？" in prompt
    assert "仅供人工核验" in prompt


def test_interpretation_prompt_rejects_unsupported_source_type() -> None:
    with pytest.raises(InterpretationSourceError, match="不支持"):
        build_interpretation_prompt("unknown", "标题", {}, None)
