"""Canonical evidence records for cold-result reviews."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


def stable_payload_hash(payload: Any) -> str:
    """Return a deterministic SHA-256 hash for JSON-compatible evidence."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evidence_record(
    *,
    event_id: int,
    category: str,
    code: str,
    value: dict[str, Any],
    phase: str,
    source_type: str,
    source_reference: str,
    observed_at: datetime,
    available_at: datetime,
    kickoff_time: datetime,
    published_at: datetime | None = None,
    direction: str | None = None,
    confidence: float = 1.0,
    verification_status: str = "verified",
) -> dict[str, Any]:
    """Build one traceable evidence record and prevent future-data leakage."""
    available_before = phase == "prematch" and available_at < kickoff_time
    hash_payload = {
        "event_id": event_id,
        "category": category,
        "code": code,
        "value": value,
        "phase": phase,
        "source_type": source_type,
        "source_reference": source_reference,
        "available_at": available_at,
    }
    return {
        "upset_event_id": event_id,
        "factor_category": category,
        "factor_code": code,
        "factor_value_json": value,
        "factor_direction": direction,
        "evidence_phase": phase,
        "available_before_kickoff": available_before,
        "source_type": source_type,
        "source_reference": source_reference,
        "published_at": published_at,
        "observed_at": observed_at,
        "available_at": available_at,
        "confidence": confidence,
        "verification_status": verification_status,
        "raw_payload_hash": stable_payload_hash(hash_payload),
    }
