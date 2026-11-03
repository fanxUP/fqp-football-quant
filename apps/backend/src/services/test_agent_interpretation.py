from __future__ import annotations

import pytest

from apps.backend.src.services.agent_interpretation import (
    InterpretationSourceError,
    build_interpretation_prompt,
    build_pre_match_source,
)


def test_pre_match_prompt_preserves_server_snapshot_and_optional_question() -> None:
    prompt = build_interpretation_prompt(
        source_type="pre_match",
        title="赛前解读：周日001",
        snapshot={"官方比赛": {"编号": "周日001"}},
        focus_question="为什么信号冲突？",
    )

    assert "官方比赛" in prompt
    assert "为什么信号冲突？" in prompt
    assert "仅供人工核验" in prompt


def test_interpretation_prompt_rejects_unsupported_source_type() -> None:
    with pytest.raises(InterpretationSourceError, match="不支持"):
        build_interpretation_prompt("unknown", "标题", {}, None)


def test_pre_match_prediction_read_scopes_canonical_selection_to_one_match() -> None:
    from datetime import datetime
    from unittest.mock import MagicMock

    kickoff = datetime(2026, 11, 4, 20, 0)
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.return_value = (
        101,
        "周三001",
        "联赛",
        "主队",
        "客队",
        kickoff,
        "scheduled",
        "selling",
    )
    cursor.fetchall.side_effect = [[], []]
    conn = MagicMock()
    conn.cursor.return_value = cursor

    build_pre_match_source(conn, 101, None)

    query, params = cursor.execute.call_args.args
    assert "model_prediction_latest_rows" not in query
    assert "g.match_id = %(match_id)s" in query
    assert "WHERE p.match_id = %(match_id)s" in query
    assert params == {"match_id": 101, "kickoff_time": kickoff}
