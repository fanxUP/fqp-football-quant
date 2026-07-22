"""Normalize auxiliary match events and statistics into review evidence values."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _minute_text(time_value: Any) -> str:
    data = time_value if isinstance(time_value, dict) else {}
    elapsed = data.get("elapsed")
    extra = data.get("extra")
    base = str(elapsed) if elapsed is not None else "未知"
    return f"{base}+{extra}" if extra not in (None, 0, "") else base


def _team_name(event: dict[str, Any], names: dict[int, str]) -> tuple[int, str]:
    team = event.get("team") if isinstance(event.get("team"), dict) else {}
    team_id = int(team.get("id") or 0)
    return team_id, names.get(team_id) or str(team.get("name") or "未知球队")


def build_event_evidence_values(
    events: list[dict[str, Any]],
    *,
    team_names_by_api_id: dict[int, str],
    observed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Keep objective goals, red cards and penalty decisions as turning points."""
    del observed_at  # timestamp is applied when values become canonical evidence rows
    values: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("type") or "").lower()
        detail = str(event.get("detail") or "")
        detail_lower = detail.lower()
        minute = _minute_text(event.get("time"))
        team_id, team_name = _team_name(event, team_names_by_api_id)
        player = event.get("player") if isinstance(event.get("player"), dict) else {}
        player_name = str(player.get("name") or "未知球员")

        code: str | None = None
        text: str | None = None
        if event_type == "goal":
            code = f"goal:{minute}:{team_id}"
            text = f"第{minute}分钟{team_name}球员{player_name}取得进球"
        elif event_type == "card" and "red" in detail_lower:
            code = f"red_card:{minute}:{team_id}"
            text = f"第{minute}分钟{team_name}球员{player_name}被红牌罚下"
        elif event_type == "var" and "penalty" in detail_lower:
            code = f"penalty_decision:{minute}:{team_id}"
            text = f"第{minute}分钟出现与{team_name}相关的点球判罚：{detail}"

        if code and text:
            values.append(
                {
                    "factor_category": "match_event",
                    "factor_code": code,
                    "factor_value_json": {"text": text, "provider_event": event},
                    "text": text,
                    "evidence_phase": "in_match",
                }
            )
    return values


_STAT_LABELS = {
    "Shots on Goal": "射正",
    "Total Shots": "射门",
    "Ball Possession": "控球率",
    "expected_goals": "预期进球",
}


def build_statistics_evidence_values(
    statistics: list[dict[str, Any]],
    *,
    team_names_by_api_id: dict[int, str],
) -> list[dict[str, Any]]:
    """Build one compact, source-preserving post-match statistics record."""
    teams: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for team_row in statistics:
        team = team_row.get("team") if isinstance(team_row.get("team"), dict) else {}
        team_id = int(team.get("id") or 0)
        team_name = team_names_by_api_id.get(team_id) or str(team.get("name") or "未知球队")
        raw_stats = team_row.get("statistics") or []
        mapped = {
            str(item.get("type")): item.get("value")
            for item in raw_stats
            if isinstance(item, dict)
            and str(item.get("type")) in _STAT_LABELS
            and item.get("value") not in (None, "")
        }
        if not mapped:
            continue
        teams.append({"team_id": team_id, "team_name": team_name, "statistics": mapped})
        rendered = []
        for stat_type, label in _STAT_LABELS.items():
            if stat_type not in mapped:
                continue
            value = mapped[stat_type]
            suffix = "次" if stat_type in {"Shots on Goal", "Total Shots"} else ""
            rendered.append(f"{label}{value}{suffix}")
        text_parts.append(f"{team_name}{'、'.join(rendered)}")

    if not teams:
        return []
    text = "；".join(text_parts)
    return [
        {
            "factor_category": "technical_statistics",
            "factor_code": "match_technical_statistics",
            "factor_value_json": {
                "text": text,
                "teams": teams,
            },
            "text": text,
            "evidence_phase": "postmatch",
        }
    ]
