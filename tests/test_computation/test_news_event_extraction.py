from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.news_event_extraction import (
    build_event_fingerprint,
    extract_rule_event,
    parse_llm_event_payload,
)


def test_official_injury_notice_becomes_verified_negative_event() -> None:
    article = {
        "title": "Club confirms striker ruled out with injury",
        "description": "The player will miss Monday's match.",
        "source_level": "S",
        "available_at": datetime(2026, 8, 10, 8, tzinfo=UTC),
        "match_id": 31,
        "home_team_name": "Home Club",
        "away_team_name": "Away Club",
    }

    event = extract_rule_event(article)

    assert event is not None
    assert event.event_type == "injury"
    assert event.direction == "negative"
    assert event.verification_status == "verified"
    assert event.confidence_score >= 0.9


def test_rumour_source_is_capped_and_requires_review() -> None:
    event = extract_rule_event(
        {
            "title": "Rumour: coach could rotate the whole team",
            "description": "Unconfirmed social post",
            "source_level": "D",
            "available_at": datetime(2026, 8, 10, 8, tzinfo=UTC),
            "match_id": 31,
            "home_team_name": "Home Club",
            "away_team_name": "Away Club",
        }
    )

    assert event is not None
    assert event.event_type == "rotation"
    assert event.verification_status == "pending"
    assert event.confidence_score <= 0.3


def test_unrelated_article_does_not_create_an_event() -> None:
    event = extract_rule_event(
        {
            "title": "Supporters remember a classic match",
            "description": "Historical feature",
            "source_level": "B",
            "available_at": datetime(2026, 8, 10, 8, tzinfo=UTC),
            "match_id": 31,
            "home_team_name": "Home Club",
            "away_team_name": "Away Club",
        }
    )

    assert event is None


def test_event_fingerprint_is_stable_for_the_same_match_cluster() -> None:
    first = build_event_fingerprint(31, "injury", "home", datetime(2026, 8, 10, 8, tzinfo=UTC))
    second = build_event_fingerprint(31, "injury", "home", datetime(2026, 8, 10, 20, tzinfo=UTC))

    assert first == second


def test_llm_event_parser_rejects_prediction_or_unknown_event_types() -> None:
    with pytest.raises(ValueError, match="不支持的新闻事件类型"):
        parse_llm_event_payload('{"eventType":"home_win","direction":"positive","summary":"主胜"}')


def test_llm_event_parser_accepts_only_fixed_structured_fields() -> None:
    payload = parse_llm_event_payload(
        '{"eventType":"suspension","direction":"negative",'
        '"summary":"球员停赛","severityScore":0.6,"confidenceScore":0.7}'
    )

    assert payload == {
        "event_type": "suspension",
        "direction": "negative",
        "summary": "球员停赛",
        "severity_score": 0.6,
        "confidence_score": 0.7,
    }
