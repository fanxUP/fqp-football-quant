from __future__ import annotations

from datetime import UTC, datetime

from apps.backend.src.services.model_gateway import ModelGatewayError, ModelReply
from scripts.news_ai_screening import build_news_screening_prompt, screen_news_article


def _article() -> dict[str, object]:
    return {
        "id": 7,
        "title": "Club confirms striker unavailable",
        "description": "The striker will miss Monday's match with an injury.",
        "source_level": "S",
        "available_at": datetime(2026, 8, 10, 8, tzinfo=UTC),
        "match_id": 31,
        "home_team_name": "Home Club",
        "away_team_name": "Away Club",
    }


def test_enabled_model_accepts_only_a_structured_news_event() -> None:
    def invoke(_prompt: str) -> ModelReply:
        return ModelReply(
            "openai",
            "gpt-5-mini",
            '{"accepted":true,"eventType":"injury","direction":"negative",'
            '"summary":"主队前锋因伤缺阵","severityScore":0.7,'
            '"confidenceScore":0.9,"relevanceScore":0.95,'
            '"entityRole":"home","requiresReview":false,"uncertainties":[]}',
        )

    result = screen_news_article(_article(), invoke_model=invoke)

    assert result.method == "llm"
    assert result.accepted is True
    assert result.draft is not None
    assert result.draft.event_type == "injury"
    assert result.draft.entity_role == "home"
    assert result.provider_code == "openai"
    assert result.model == "gpt-5-mini"


def test_model_rejection_is_archived_without_creating_an_event() -> None:
    def invoke(_prompt: str) -> ModelReply:
        return ModelReply(
            "openai",
            "gpt-5-mini",
            '{"accepted":false,"reasonCode":"unrelated","requiresReview":false,"uncertainties":[]}',
        )

    result = screen_news_article(_article(), invoke_model=invoke)

    assert result.method == "llm"
    assert result.accepted is False
    assert result.draft is None
    assert result.reason_code == "unrelated"


def test_model_failure_falls_back_to_existing_rule_extraction() -> None:
    def invoke(_prompt: str) -> ModelReply:
        raise ModelGatewayError("provider unavailable")

    result = screen_news_article(_article(), invoke_model=invoke)

    assert result.method == "rule_fallback"
    assert result.accepted is True
    assert result.draft is not None
    assert result.draft.event_type == "injury"
    assert result.error_code == "MODEL_CALL_FAILED"


def test_unconfigured_model_keeps_deterministic_rule_behavior() -> None:
    result = screen_news_article(_article(), invoke_model=None)

    assert result.method == "rule"
    assert result.accepted is True
    assert result.draft is not None
    assert result.provider_code is None


def test_prompt_contains_only_bounded_server_side_article_material() -> None:
    article = _article()
    article["description"] = "x" * 10_000

    prompt = build_news_screening_prompt(article)

    assert len(prompt) < 8_000
    assert "不得预测" in prompt
    assert '"matchId": 31' in prompt
