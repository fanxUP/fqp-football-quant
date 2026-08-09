"""Immutable, backend-built source snapshots for generated reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

_MATCH_CARD_FIELDS = (
    "matchId",
    "officialCode",
    "leagueName",
    "homeTeamName",
    "awayTeamName",
    "kickoffTime",
    "result",
    "modelSignals",
    "oddsSignals",
    "evidence",
    "evidenceStatus",
)


def build_daily_report_snapshot(
    *,
    review: Mapping[str, Any],
    upset_report: Mapping[str, Any],
    match_cards: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Freeze read-only facts used for a daily post-match report.

    Match cards are assembled on the backend from confirmed official results,
    pre-kickoff predictions, final available official odds, and stored evidence.
    This helper deliberately omits any mutable frontend input.
    """
    matches = [
        {field: deepcopy(card.get(field)) for field in _MATCH_CARD_FIELDS}
        for card in match_cards
    ]
    return {
        "schemaVersion": 1,
        "sourceNotice": (
            "比赛、赛果、赛前模型信号和官方赔率均由后端只读归档；"
            "证据缺失时明确标记为未查到可靠资料。"
        ),
        "dailyReview": deepcopy(dict(review)),
        "matches": matches,
        "upsetReport": deepcopy(dict(upset_report)),
    }
