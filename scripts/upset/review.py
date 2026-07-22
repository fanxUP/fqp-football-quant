"""Evidence-grounded structured cold-result review generation."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _evidence_text(row: dict[str, Any]) -> str | None:
    value = row.get("factor_value_json")
    if isinstance(value, dict) and value.get("text"):
        return str(value["text"])
    return None


def validate_review_payload(
    payload: dict[str, Any],
    *,
    evidence_by_id: dict[int, dict[str, Any]],
    kickoff_time: datetime,
) -> list[str]:
    """Reject untraceable facts and post-kickoff evidence presented as prematch."""
    errors: list[str] = []
    for fact in payload.get("facts_json", []):
        evidence_id = fact.get("evidence_id") if isinstance(fact, dict) else None
        if not evidence_id or int(evidence_id) not in evidence_by_id:
            errors.append("FACT_WITHOUT_EVIDENCE")

    for signal in payload.get("prematch_signals_json", []):
        evidence_id = signal.get("evidence_id") if isinstance(signal, dict) else None
        evidence = evidence_by_id.get(int(evidence_id)) if evidence_id else None
        available_at = _as_datetime(evidence.get("available_at")) if evidence else None
        if (
            not evidence
            or not evidence.get("available_before_kickoff")
            or available_at is None
            or available_at >= kickoff_time
        ):
            errors.append("PREMATCH_USES_FUTURE_EVIDENCE")
    return sorted(set(errors))


def _completeness(evidence: list[dict[str, Any]], model_postmortem: dict[str, Any]) -> float:
    categories = {str(row.get("factor_category")) for row in evidence}
    score = 0.0
    if "official_result" in categories:
        score += 0.25
    if "market" in categories:
        score += 0.25
    if model_postmortem.get("status") != "unavailable":
        score += 0.20
    if "feature" in categories:
        score += 0.15
    if any(row.get("evidence_phase") == "in_match" for row in evidence):
        score += 0.10
    if "technical_statistics" in categories:
        score += 0.05
    return min(score, 1.0)


def build_review_payload(
    *,
    event: dict[str, Any],
    evidence: list[dict[str, Any]],
    kickoff_time: datetime,
    model_postmortem: dict[str, Any],
) -> dict[str, Any]:
    """Build a conservative review without inventing causal explanations."""
    verified = [row for row in evidence if row.get("verification_status") == "verified"]
    facts = [
        {"text": text, "evidence_id": int(row["id"])}
        for row in verified
        if row.get("factor_category") != "provider_capture"
        if (text := _evidence_text(row))
    ]
    prematch = [
        {"text": text, "evidence_id": int(row["id"])}
        for row in verified
        if row.get("available_before_kickoff")
        and (_as_datetime(row.get("available_at")) or kickoff_time) < kickoff_time
        and (text := _evidence_text(row))
    ]
    turning_points = [
        {"text": text, "evidence_id": int(row["id"])}
        for row in verified
        if row.get("evidence_phase") == "in_match"
        and (text := _evidence_text(row))
    ]
    level = event.get("upset_level")
    classification = f"{level}级冷门" if level else "热门未打出事件"
    if facts:
        summary = f"该场被识别为{classification}；当前复盘仅陈述已验证证据，不对缺失信息作推断。"
    else:
        summary = f"该场已识别为{classification}，暂无充分证据解释形成原因。"

    completeness = _completeness(verified, model_postmortem)
    payload = {
        "summary": summary,
        "facts_json": facts,
        "prematch_signals_json": prematch,
        "in_match_turning_points_json": turning_points,
        "inferences_json": [],
        "hypotheses_json": [],
        "randomness_json": [],
        "model_postmortem_json": model_postmortem,
        "actionable_lessons_json": [],
        "data_completeness": completeness,
        "confidence": completeness,
        "validation_status": "validated" if completeness >= 0.5 else "waiting_data",
        "validation_errors_json": [],
    }
    evidence_by_id = {int(row["id"]): row for row in verified}
    errors = validate_review_payload(
        payload,
        evidence_by_id=evidence_by_id,
        kickoff_time=kickoff_time,
    )
    if errors:
        payload["validation_status"] = "invalid"
        payload["validation_errors_json"] = errors
    return payload
