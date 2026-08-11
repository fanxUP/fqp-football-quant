"""Persistence for auditable news screening, extraction and corroboration."""

from __future__ import annotations

from typing import Any

from psycopg2.extras import Json

from apps.backend.src.services.model_gateway import invoke_agent_model
from apps.backend.src.services.model_invocation_audit import record_model_invocation
from apps.backend.src.services.model_provider_store import get_agent_model_binding
from scripts.news_ai_screening import NewsScreeningResult, screen_news_article

_NEWS_AGENT = "news_extraction_agent"


def _ready_model_invoker(conn: Any):
    binding = get_agent_model_binding(conn, _NEWS_AGENT)
    if not binding or not binding["enabled"] or binding["last_test_status"] != "passed":
        return None
    return lambda prompt: invoke_agent_model(conn, _NEWS_AGENT, prompt)


def _store_screening(
    conn: Any,
    *,
    article_id: int,
    match_id: int,
    result: NewsScreeningResult,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO news_article_screenings (
                article_id, match_id, screening_method, accepted, reason_code,
                relevance_score, requires_review, normalized_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (article_id, match_id) DO UPDATE SET
                screening_method = EXCLUDED.screening_method,
                accepted = EXCLUDED.accepted,
                reason_code = EXCLUDED.reason_code,
                relevance_score = EXCLUDED.relevance_score,
                requires_review = EXCLUDED.requires_review,
                normalized_payload = EXCLUDED.normalized_payload
            RETURNING id
            """,
            (
                article_id,
                match_id,
                result.method,
                result.accepted,
                result.reason_code,
                result.relevance_score,
                result.requires_review,
                Json(result.normalized_payload),
            ),
        )
        screening_id = int(cur.fetchone()[0])
        if result.prompt_sha256:
            status = "failed" if result.error_code else "succeeded"
            cur.execute(
                """
                INSERT INTO news_model_invocations (
                    screening_id, article_id, match_id, provider_code, model, status,
                    prompt_sha256, response_sha256, duration_ms, error_code
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    screening_id,
                    article_id,
                    match_id,
                    result.provider_code,
                    result.model,
                    status,
                    result.prompt_sha256,
                    result.response_sha256,
                    result.duration_ms,
                    result.error_code,
                ),
            )
            record_model_invocation(
                conn,
                agent_code=_NEWS_AGENT,
                provider_code=result.provider_code,
                model=result.model,
                status=status,
                prompt_length=0,
                response_length=0,
                duration_ms=result.duration_ms,
                error_code=result.error_code,
                commit=False,
            )
    return screening_id


def process_pending_news_articles(conn: Any, limit: int = 200) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT article.id, article.title, article.description, article.available_at,
                   source.source_level, link.match_id, match.home_team_name,
                   match.away_team_name
            FROM news_articles_raw article
            JOIN news_sources source ON source.id = article.source_id
            JOIN news_article_matches link ON link.article_id = article.id
            JOIN official_matches match ON match.id = link.match_id
            WHERE NOT EXISTS (
                SELECT 1 FROM news_article_screenings screening
                WHERE screening.article_id = article.id
                  AND screening.match_id = link.match_id
            )
            ORDER BY article.available_at, article.id
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    invoke_model = _ready_model_invoker(conn)
    created = 0
    skipped = 0
    evidence_added = 0
    model_screened = 0
    model_failures = 0
    rule_screened = 0
    for row in rows:
        article = {
            "id": row[0],
            "title": row[1],
            "description": row[2],
            "available_at": row[3],
            "source_level": row[4],
            "match_id": row[5],
            "home_team_name": row[6],
            "away_team_name": row[7],
        }
        result = screen_news_article(article, invoke_model=invoke_model)
        screening_id = _store_screening(
            conn,
            article_id=row[0],
            match_id=row[5],
            result=result,
        )
        model_screened += int(result.method == "llm")
        model_failures += int(result.method == "rule_fallback")
        rule_screened += int(result.method in {"rule", "rule_fallback"})
        draft = result.draft
        if draft is None:
            skipped += 1
            continue
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_events (
                    event_fingerprint, event_type, direction, title, summary,
                    severity_score, confidence_score, verification_status,
                    first_available_at, extraction_method, extraction_version,
                    match_relevance_score, extraction_metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_fingerprint) DO UPDATE SET
                    severity_score = GREATEST(news_events.severity_score, EXCLUDED.severity_score),
                    confidence_score = GREATEST(news_events.confidence_score, EXCLUDED.confidence_score),
                    first_available_at = LEAST(news_events.first_available_at, EXCLUDED.first_available_at),
                    updated_at = NOW()
                RETURNING id, (xmax = 0) AS inserted
                """,
                (
                    draft.event_fingerprint,
                    draft.event_type,
                    draft.direction,
                    draft.title,
                    draft.summary,
                    draft.severity_score,
                    draft.confidence_score,
                    draft.verification_status,
                    draft.first_available_at,
                    "llm" if result.method == "llm" else "rule",
                    "news-llm-v1" if result.method == "llm" else "news-rule-v1",
                    result.relevance_score,
                    Json(
                        {
                            "screeningId": screening_id,
                            "screeningMethod": result.method,
                            "requiresReview": result.requires_review,
                        }
                    ),
                ),
            )
            event_id, inserted = cur.fetchone()
            cur.execute(
                """
                INSERT INTO news_event_entities (
                    event_id, match_id, entity_role, entity_name, link_confidence
                )
                VALUES (%s, %s, %s, %s, 1)
                ON CONFLICT DO NOTHING
                """,
                (
                    event_id,
                    row[5],
                    draft.entity_role,
                    row[6] if draft.entity_role == "home" else row[7]
                    if draft.entity_role == "away"
                    else None,
                ),
            )
            cur.execute(
                """
                INSERT INTO news_event_evidence (
                    event_id, article_id, evidence_role, verification_status, available_at
                )
                VALUES (%s, %s, 'primary', %s, %s)
                ON CONFLICT (event_id, article_id) DO NOTHING
                RETURNING id
                """,
                (
                    event_id,
                    row[0],
                    draft.verification_status,
                    row[3],
                ),
            )
            evidence_added += int(cur.fetchone() is not None)
            cur.execute(
                """
                UPDATE news_events event
                SET verification_status = 'verified', verified_at = NOW(), updated_at = NOW()
                WHERE event.id = %s
                  AND event.verification_status = 'pending'
                  AND (
                    EXISTS (
                        SELECT 1
                        FROM news_event_evidence evidence
                        JOIN news_articles_raw article ON article.id = evidence.article_id
                        JOIN news_sources source ON source.id = article.source_id
                        WHERE evidence.event_id = event.id
                          AND source.source_level IN ('S', 'A')
                    )
                    OR 2 <= (
                        SELECT COUNT(DISTINCT article.source_id)
                        FROM news_event_evidence evidence
                        JOIN news_articles_raw article ON article.id = evidence.article_id
                        JOIN news_sources source ON source.id = article.source_id
                        WHERE evidence.event_id = event.id
                          AND source.source_level IN ('B', 'C')
                    )
                  )
                """,
                (event_id,),
            )
        created += int(bool(inserted))
    conn.commit()
    return {
        "status": "ok",
        "processed": len(rows),
        "eventsCreated": created,
        "evidenceAdded": evidence_added,
        "skipped": skipped,
        "modelScreened": model_screened,
        "modelFailures": model_failures,
        "ruleScreened": rule_screened,
    }
