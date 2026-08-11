from datetime import UTC, datetime, timedelta

from scripts.news_feature_snapshots import (
    FEATURE_VERSION,
    build_feature_vector,
    snapshot_cutoff,
)

KICKOFF = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def test_snapshot_cutoffs_are_fixed_relative_to_kickoff() -> None:
    assert snapshot_cutoff(KICKOFF, "T24H") == KICKOFF - timedelta(hours=24)
    assert snapshot_cutoff(KICKOFF, "T6H") == KICKOFF - timedelta(hours=6)
    assert snapshot_cutoff(KICKOFF, "T90M") == KICKOFF - timedelta(minutes=90)
    assert snapshot_cutoff(KICKOFF, "T45M") == KICKOFF - timedelta(minutes=45)
    assert snapshot_cutoff(KICKOFF, "POST120") == KICKOFF + timedelta(minutes=120)


def test_feature_vector_uses_verified_directional_events_only() -> None:
    events = [
        {
            "eventType": "injury",
            "direction": "negative",
            "entityRole": "home",
            "severityScore": 0.8,
            "confidenceScore": 0.9,
            "verificationStatus": "verified",
            "sourceCount": 2,
        },
        {
            "eventType": "return",
            "direction": "positive",
            "entityRole": "away",
            "severityScore": 0.5,
            "confidenceScore": 0.8,
            "verificationStatus": "verified",
            "sourceCount": 1,
        },
        {
            "eventType": "suspension",
            "direction": "negative",
            "entityRole": "away",
            "severityScore": 1.0,
            "confidenceScore": 1.0,
            "verificationStatus": "pending",
            "sourceCount": 1,
        },
    ]

    vector = build_feature_vector(events)

    assert vector["featureVersion"] == FEATURE_VERSION
    assert vector["verifiedEventCount"] == 2
    assert vector["pendingEventCount"] == 1
    assert vector["homeNegativeImpact"] == 0.72
    assert vector["awayPositiveImpact"] == 0.4
    assert vector["homeNetImpact"] == -0.72
    assert vector["awayNetImpact"] == 0.4
    assert vector["evidenceCount"] == 4


def test_feature_values_are_bounded_even_with_many_events() -> None:
    events = [
        {
            "eventType": "injury",
            "direction": "negative",
            "entityRole": "home",
            "severityScore": 1,
            "confidenceScore": 1,
            "verificationStatus": "verified",
            "sourceCount": 1,
        }
        for _ in range(20)
    ]

    vector = build_feature_vector(events)

    assert vector["homeNegativeImpact"] == 1.0
    assert vector["homeNetImpact"] == -1.0
