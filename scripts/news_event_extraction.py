"""Deterministic and strictly bounded news-event extraction primitives."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

EVENT_TYPES = {
    "injury",
    "suspension",
    "return",
    "expected_lineup",
    "official_lineup",
    "rotation",
    "manager_change",
    "schedule_pressure",
    "internal_issue",
    "morale_positive",
    "morale_negative",
}
DIRECTIONS = {"positive", "negative", "neutral"}

_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("suspension", ("suspended", "suspension", "match ban", "停赛", "禁赛")),
    ("return", ("returns from injury", "fit again", "back in training", "复出", "伤愈")),
    ("official_lineup", ("confirmed lineup", "official lineup", "starting xi confirmed", "官方首发", "首发名单")),
    ("expected_lineup", ("expected lineup", "predicted lineup", "预计首发")),
    ("rotation", ("rotate", "rotation", "rest players", "轮换", "轮休")),
    ("manager_change", ("sacked", "appointed head coach", "new manager", "主帅下课", "新任主帅")),
    ("schedule_pressure", ("fixture congestion", "short turnaround", "密集赛程", "连续客场")),
    ("internal_issue", ("dressing room", "internal conflict", "unpaid wages", "内部矛盾", "欠薪")),
    ("morale_positive", ("contract extension", "boost", "士气提升", "续约")),
    ("morale_negative", ("low morale", "crisis", "士气低落", "危机")),
    ("injury", ("ruled out", "injured", "injury", "unavailable", "受伤", "伤缺", "缺阵")),
)

_DIRECTION = {
    "return": "positive",
    "morale_positive": "positive",
    "official_lineup": "neutral",
    "expected_lineup": "neutral",
}
_SEVERITY = {
    "injury": 0.7,
    "suspension": 0.65,
    "return": 0.45,
    "expected_lineup": 0.25,
    "official_lineup": 0.4,
    "rotation": 0.55,
    "manager_change": 0.7,
    "schedule_pressure": 0.45,
    "internal_issue": 0.6,
    "morale_positive": 0.35,
    "morale_negative": 0.45,
}
_SOURCE_CONFIDENCE = {"S": 0.98, "A": 0.92, "B": 0.75, "C": 0.5, "D": 0.25}


@dataclass(frozen=True)
class EventDraft:
    event_type: str
    direction: str
    title: str
    summary: str
    severity_score: float
    confidence_score: float
    verification_status: str
    first_available_at: datetime
    entity_role: str
    event_fingerprint: str


def build_event_fingerprint(
    match_id: int,
    event_type: str,
    entity_role: str,
    available_at: datetime,
) -> str:
    cluster = f"{match_id}|{event_type}|{entity_role}|{available_at.date().isoformat()}"
    return hashlib.sha256(cluster.encode("utf-8")).hexdigest()


def _entity_role(text: str, home_name: str, away_name: str) -> str:
    if home_name and home_name.casefold() in text:
        return "home"
    if away_name and away_name.casefold() in text:
        return "away"
    return "related"


def extract_rule_event(article: dict[str, Any]) -> EventDraft | None:
    title = str(article.get("title") or "").strip()
    description = str(article.get("description") or "").strip()
    text = f"{title}\n{description}".casefold()
    event_type = next(
        (candidate for candidate, keywords in _RULES if any(keyword in text for keyword in keywords)),
        None,
    )
    if event_type is None:
        return None
    source_level = str(article.get("source_level") or "D").upper()
    available_at = article.get("available_at")
    match_id = article.get("match_id")
    if not isinstance(available_at, datetime) or not isinstance(match_id, int):
        raise ValueError("新闻事件缺少有效的比赛或可用时间")
    role = _entity_role(
        text,
        str(article.get("home_team_name") or ""),
        str(article.get("away_team_name") or ""),
    )
    confidence = _SOURCE_CONFIDENCE.get(source_level, _SOURCE_CONFIDENCE["D"])
    return EventDraft(
        event_type=event_type,
        direction=_DIRECTION.get(event_type, "negative"),
        title=title[:500],
        summary=(description or title)[:2000],
        severity_score=_SEVERITY[event_type],
        confidence_score=confidence,
        verification_status="verified" if source_level in {"S", "A"} else "pending",
        first_available_at=available_at,
        entity_role=role,
        event_fingerprint=build_event_fingerprint(match_id, event_type, role, available_at),
    )


def parse_llm_event_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("模型未返回有效的新闻事件 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("模型新闻事件必须是 JSON 对象")
    event_type = str(payload.get("eventType") or "")
    direction = str(payload.get("direction") or "")
    if event_type not in EVENT_TYPES:
        raise ValueError("不支持的新闻事件类型")
    if direction not in DIRECTIONS:
        raise ValueError("不支持的新闻事件方向")
    summary = str(payload.get("summary") or "").strip()
    if not summary or len(summary) > 2000:
        raise ValueError("新闻事件摘要不能为空且不能超过 2000 字")
    try:
        severity = float(str(payload.get("severityScore")))
        confidence = float(str(payload.get("confidenceScore")))
    except ValueError as exc:
        raise ValueError("新闻事件评分必须是数字") from exc
    if not 0 <= severity <= 1 or not 0 <= confidence <= 1:
        raise ValueError("新闻事件评分必须位于 0 到 1")
    return {
        "event_type": event_type,
        "direction": direction,
        "summary": summary,
        "severity_score": severity,
        "confidence_score": confidence,
    }
