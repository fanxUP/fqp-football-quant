"""Bounded model-assisted screening for already discovered football news."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any

from apps.backend.src.services.model_gateway import ModelGatewayError, ModelReply
from scripts.news_event_extraction import (
    DIRECTIONS,
    EVENT_TYPES,
    EventDraft,
    build_event_fingerprint,
    extract_rule_event,
)

_AGENT_CODE = "news_extraction_agent"
_ENTITY_ROLES = {"home", "away", "related"}
_REJECTION_REASONS = {"unrelated", "duplicate", "stale", "insufficient_evidence"}
_SOURCE_CONFIDENCE_CAP = {"S": 0.98, "A": 0.92, "B": 0.75, "C": 0.5, "D": 0.25}
_ACCEPTED_FIELDS = {
    "accepted",
    "eventType",
    "direction",
    "summary",
    "severityScore",
    "confidenceScore",
    "relevanceScore",
    "entityRole",
    "requiresReview",
    "uncertainties",
}
_REJECTED_FIELDS = {"accepted", "reasonCode", "requiresReview", "uncertainties"}


@dataclass(frozen=True)
class NewsScreeningResult:
    accepted: bool
    method: str
    reason_code: str
    relevance_score: float
    requires_review: bool
    draft: EventDraft | None
    normalized_payload: dict[str, Any]
    provider_code: str | None = None
    model: str | None = None
    prompt_sha256: str | None = None
    response_sha256: str | None = None
    duration_ms: int = 0
    error_code: str | None = None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_news_screening_prompt(article: dict[str, Any]) -> str:
    """Build a server-owned prompt; browser input never enters this material."""
    material = {
        "articleId": article.get("id"),
        "matchId": article.get("match_id"),
        "homeTeam": str(article.get("home_team_name") or "")[:160],
        "awayTeam": str(article.get("away_team_name") or "")[:160],
        "sourceLevel": str(article.get("source_level") or "D")[:1],
        "publishedOrObservedAt": str(article.get("available_at") or ""),
        "title": str(article.get("title") or "")[:500],
        "description": str(article.get("description") or "")[:2_000],
    }
    schema = {
        "accepted": True,
        "eventType": "injury",
        "direction": "negative",
        "summary": "只复述材料中可确认的事实",
        "severityScore": 0.0,
        "confidenceScore": 0.0,
        "relevanceScore": 0.0,
        "entityRole": "home|away|related",
        "requiresReview": True,
        "uncertainties": [],
    }
    return (
        "判断文章是否包含与指定比赛直接相关的足球事件，并只返回一个 JSON 对象。"
        "不得预测赛果、不得推荐投注、不得补充材料外事实。"
        "无关或证据不足时返回 accepted=false，并使用 reasonCode："
        "unrelated、duplicate、stale 或 insufficient_evidence。"
        f"允许的 eventType：{','.join(sorted(EVENT_TYPES))}。"
        f"允许的 direction：{','.join(sorted(DIRECTIONS))}。"
        "不要输出 Markdown 或额外字段。\n"
        f"accepted=true 格式：{json.dumps(schema, ensure_ascii=False)}\n"
        "accepted=false 格式："
        '{"accepted":false,"reasonCode":"unrelated",'
        '"requiresReview":false,"uncertainties":[]}\n'
        f"后端材料：{json.dumps(material, ensure_ascii=False, default=str, sort_keys=True)}"
    )


def _number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} 必须是数字")
    try:
        number = float(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} 必须是数字") from exc
    if not 0 <= number <= 1:
        raise ValueError(f"{key} 必须位于 0 到 1")
    return number


def parse_news_screening_payload(raw: str) -> dict[str, Any]:
    """Accept only the documented, bounded JSON contract."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("模型未返回有效的新闻筛选 JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("accepted"), bool):
        raise ValueError("模型新闻筛选结果必须包含布尔 accepted")
    allowed = _ACCEPTED_FIELDS if payload["accepted"] else _REJECTED_FIELDS
    if set(payload) - allowed:
        raise ValueError("模型新闻筛选结果包含未允许字段")
    uncertainties = payload.get("uncertainties", [])
    if not isinstance(uncertainties, list) or len(uncertainties) > 8:
        raise ValueError("uncertainties 必须是最多 8 项的数组")
    normalized_uncertainties = [str(item)[:240] for item in uncertainties]
    requires_review = payload.get("requiresReview", True)
    if not isinstance(requires_review, bool):
        raise ValueError("requiresReview 必须是布尔值")
    if not payload["accepted"]:
        reason_code = str(payload.get("reasonCode") or "")
        if reason_code not in _REJECTION_REASONS:
            raise ValueError("模型新闻拒绝原因不受支持")
        return {
            "accepted": False,
            "reason_code": reason_code,
            "requires_review": requires_review,
            "uncertainties": normalized_uncertainties,
        }

    event_type = str(payload.get("eventType") or "")
    direction = str(payload.get("direction") or "")
    entity_role = str(payload.get("entityRole") or "")
    summary = str(payload.get("summary") or "").strip()
    if event_type not in EVENT_TYPES:
        raise ValueError("不支持的新闻事件类型")
    if direction not in DIRECTIONS:
        raise ValueError("不支持的新闻事件方向")
    if entity_role not in _ENTITY_ROLES:
        raise ValueError("不支持的新闻实体角色")
    if not summary or len(summary) > 2_000:
        raise ValueError("新闻事件摘要不能为空且不能超过 2000 字")
    return {
        "accepted": True,
        "event_type": event_type,
        "direction": direction,
        "summary": summary,
        "severity_score": _number(payload, "severityScore"),
        "confidence_score": _number(payload, "confidenceScore"),
        "relevance_score": _number(payload, "relevanceScore"),
        "entity_role": entity_role,
        "requires_review": requires_review,
        "uncertainties": normalized_uncertainties,
    }


def _rule_result(
    article: dict[str, Any],
    *,
    method: str,
    error_code: str | None = None,
    provider_code: str | None = None,
    model: str | None = None,
    prompt_sha256: str | None = None,
    response_sha256: str | None = None,
    duration_ms: int = 0,
) -> NewsScreeningResult:
    draft = extract_rule_event(article)
    return NewsScreeningResult(
        accepted=draft is not None,
        method=method,
        reason_code="rule_match" if draft else "no_rule_signal",
        relevance_score=1.0 if draft else 0.0,
        requires_review=bool(draft and draft.verification_status != "verified"),
        draft=draft,
        normalized_payload={},
        provider_code=provider_code,
        model=model,
        prompt_sha256=prompt_sha256,
        response_sha256=response_sha256,
        duration_ms=duration_ms,
        error_code=error_code,
    )


def screen_news_article(
    article: dict[str, Any],
    *,
    invoke_model: Callable[[str], ModelReply] | None,
) -> NewsScreeningResult:
    """Use one ready Agent call, otherwise preserve deterministic extraction."""
    if invoke_model is None:
        return _rule_result(article, method="rule")

    prompt = build_news_screening_prompt(article)
    started_at = perf_counter()
    reply: ModelReply | None = None
    try:
        reply = invoke_model(prompt)
        payload = parse_news_screening_payload(reply.content)
    except ModelGatewayError, ValueError:
        duration_ms = round((perf_counter() - started_at) * 1_000)
        return _rule_result(
            article,
            method="rule_fallback",
            error_code="MODEL_CALL_FAILED" if reply is None else "INVALID_MODEL_OUTPUT",
            provider_code=reply.provider_code if reply else None,
            model=reply.model if reply else None,
            prompt_sha256=_sha256(prompt),
            response_sha256=_sha256(reply.content) if reply else None,
            duration_ms=duration_ms,
        )

    duration_ms = round((perf_counter() - started_at) * 1_000)
    prompt_sha256 = _sha256(prompt)
    response_sha256 = _sha256(reply.content)
    if not payload["accepted"]:
        return NewsScreeningResult(
            accepted=False,
            method="llm",
            reason_code=payload["reason_code"],
            relevance_score=0.0,
            requires_review=payload["requires_review"],
            draft=None,
            normalized_payload=payload,
            provider_code=reply.provider_code,
            model=reply.model,
            prompt_sha256=prompt_sha256,
            response_sha256=response_sha256,
            duration_ms=duration_ms,
        )

    source_level = str(article.get("source_level") or "D").upper()
    confidence = min(payload["confidence_score"], _SOURCE_CONFIDENCE_CAP.get(source_level, 0.25))
    available_at = article.get("available_at")
    match_id = article.get("match_id")
    if not isinstance(available_at, datetime) or not isinstance(match_id, int):
        raise ValueError("新闻事件缺少有效的比赛或可用时间")
    verification_status = (
        "verified" if source_level in {"S", "A"} and not payload["requires_review"] else "pending"
    )
    draft = EventDraft(
        event_type=payload["event_type"],
        direction=payload["direction"],
        title=str(article.get("title") or "")[:500],
        summary=payload["summary"],
        severity_score=payload["severity_score"],
        confidence_score=confidence,
        verification_status=verification_status,
        first_available_at=available_at,
        entity_role=payload["entity_role"],
        event_fingerprint=build_event_fingerprint(
            match_id, payload["event_type"], payload["entity_role"], available_at
        ),
    )
    return NewsScreeningResult(
        accepted=True,
        method="llm",
        reason_code="accepted",
        relevance_score=payload["relevance_score"],
        requires_review=payload["requires_review"],
        draft=draft,
        normalized_payload=payload,
        provider_code=reply.provider_code,
        model=reply.model,
        prompt_sha256=prompt_sha256,
        response_sha256=response_sha256,
        duration_ms=duration_ms,
    )
