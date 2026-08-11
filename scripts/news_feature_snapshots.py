"""Pure point-in-time transforms for isolated football-news features."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

FEATURE_VERSION = "news-features-v1"
SnapshotLabel = Literal["T24H", "T6H", "T90M", "T45M", "POST120"]
SNAPSHOT_LABELS: tuple[SnapshotLabel, ...] = (
    "T24H",
    "T6H",
    "T90M",
    "T45M",
    "POST120",
)

_OFFSETS = {
    "T24H": timedelta(hours=-24),
    "T6H": timedelta(hours=-6),
    "T90M": timedelta(minutes=-90),
    "T45M": timedelta(minutes=-45),
    "POST120": timedelta(minutes=120),
}


def snapshot_cutoff(kickoff: datetime, label: SnapshotLabel) -> datetime:
    return kickoff + _OFFSETS[label]


def _bounded(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 6)


def build_feature_vector(events: list[dict[str, Any]]) -> dict[str, Any]:
    impacts = {
        "homePositiveImpact": 0.0,
        "homeNegativeImpact": 0.0,
        "awayPositiveImpact": 0.0,
        "awayNegativeImpact": 0.0,
    }
    verified = 0
    pending = 0
    evidence_count = 0
    confidence_total = 0.0
    for event in events:
        evidence_count += max(0, int(event.get("sourceCount") or 0))
        if event.get("verificationStatus") != "verified":
            pending += 1
            continue
        verified += 1
        confidence = _bounded(float(event.get("confidenceScore") or 0))
        severity = _bounded(float(event.get("severityScore") or 0))
        confidence_total += confidence
        role = str(event.get("entityRole") or "")
        direction = str(event.get("direction") or "neutral")
        if role not in {"home", "away"} or direction not in {"positive", "negative"}:
            continue
        key = f"{role}{direction.title()}Impact"
        impacts[key] = _bounded(impacts[key] + severity * confidence)

    total = verified + pending
    return {
        "featureVersion": FEATURE_VERSION,
        **impacts,
        "homeNetImpact": round(
            impacts["homePositiveImpact"] - impacts["homeNegativeImpact"], 6
        ),
        "awayNetImpact": round(
            impacts["awayPositiveImpact"] - impacts["awayNegativeImpact"], 6
        ),
        "verifiedEventCount": verified,
        "pendingEventCount": pending,
        "evidenceCount": evidence_count,
        "coverageScore": _bounded(verified / total) if total else 0.0,
        "confidenceScore": _bounded(confidence_total / verified) if verified else 0.0,
    }
