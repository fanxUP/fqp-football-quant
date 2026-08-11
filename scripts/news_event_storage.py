"""Persistence for deterministic news-event extraction and corroboration."""

from __future__ import annotations

from typing import Any

from scripts.news_event_extraction import extract_rule_event


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
                SELECT 1 FROM news_event_evidence evidence
                WHERE evidence.article_id = article.id
            )
            ORDER BY article.available_at, article.id
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    created = 0
    skipped = 0
    evidence_added = 0
    for row in rows:
        article = {
            "title": row[1],
            "description": row[2],
            "available_at": row[3],
            "source_level": row[4],
            "match_id": row[5],
            "home_team_name": row[6],
            "away_team_name": row[7],
        }
        draft = extract_rule_event(article)
        if draft is None:
            skipped += 1
            continue
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_events (
                    event_fingerprint, event_type, direction, title, summary,
                    severity_score, confidence_score, verification_status,
                    first_available_at, extraction_method, extraction_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'rule', 'news-rule-v1')
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
                    "verified" if row[4] in {"S", "A"} else "pending",
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
    }
