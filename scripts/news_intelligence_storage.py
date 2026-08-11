"""Append-only storage for normalized news discovery candidates."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from psycopg2.extras import Json

from scripts.news_intelligence_clients import NewsArticleCandidate


def load_news_watch_matches(conn: Any, limit: int = 80) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, official_match_code, home_team_name, away_team_name, kickoff_time
            FROM official_matches
            WHERE official_match_code IS NOT NULL
              AND kickoff_time BETWEEN timezone('Asia/Shanghai', NOW())
                                   AND timezone('Asia/Shanghai', NOW()) + INTERVAL '36 hours'
            ORDER BY kickoff_time, id
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "official_match_code": row[1],
            "home_team_name": row[2],
            "away_team_name": row[3],
            "kickoff_time": row[4],
        }
        for row in rows
    ]


def _matching_matches(
    candidate: NewsArticleCandidate,
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text = f"{candidate.title}\n{candidate.description}".casefold()
    return [
        match
        for match in matches
        if str(match["home_team_name"]).casefold() in text
        or str(match["away_team_name"]).casefold() in text
    ]


def store_news_candidates(
    conn: Any,
    candidates: list[NewsArticleCandidate],
    matches: list[dict[str, Any]],
    *,
    observed_at: datetime,
) -> dict[str, int]:
    inserted = 0
    duplicates = 0
    linked = 0
    for candidate in candidates:
        source_code = "publisher:" + hashlib.sha256(candidate.source_domain.encode()).hexdigest()[:24]
        content_hash = hashlib.sha256(
            f"{candidate.title}\n{candidate.description}".encode()
        ).hexdigest()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_sources (
                    source_code, source_name, publisher_domain, source_level, source_type,
                    default_language, last_success_at, last_error
                )
                VALUES (%s, %s, %s, 'C', 'media', %s, NOW(), NULL)
                ON CONFLICT (source_code) DO UPDATE SET
                    source_name = EXCLUDED.source_name,
                    last_success_at = NOW(), last_error = NULL, updated_at = NOW()
                RETURNING id
                """,
                (
                    source_code,
                    candidate.source_name,
                    candidate.source_domain,
                    candidate.language,
                ),
            )
            source_id = cur.fetchone()[0]
            available_at = max(candidate.published_at, observed_at)
            cur.execute(
                """
                INSERT INTO news_articles_raw (
                    provider_code, external_id, source_id, canonical_url, title,
                    description, language, published_at, observed_at, available_at,
                    content_hash, raw_metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (canonical_url) DO NOTHING
                RETURNING id
                """,
                (
                    candidate.provider_code,
                    candidate.external_id,
                    source_id,
                    candidate.canonical_url,
                    candidate.title,
                    candidate.description,
                    candidate.language,
                    candidate.published_at,
                    observed_at,
                    available_at,
                    content_hash,
                    Json(candidate.raw_metadata),
                ),
            )
            row = cur.fetchone()
            if row:
                article_id = row[0]
                inserted += 1
            else:
                duplicates += 1
                cur.execute(
                    "SELECT id FROM news_articles_raw WHERE canonical_url = %s",
                    (candidate.canonical_url,),
                )
                existing = cur.fetchone()
                if not existing:
                    continue
                article_id = existing[0]
            for match in _matching_matches(candidate, matches):
                cur.execute(
                    """
                    INSERT INTO news_article_matches (
                        article_id, match_id, relevance_score, link_method
                    )
                    VALUES (%s, %s, 0.8, 'entity_match')
                    ON CONFLICT DO NOTHING
                    RETURNING article_id
                    """,
                    (article_id, match["id"]),
                )
                linked += int(cur.fetchone() is not None)
    conn.commit()
    return {"inserted": inserted, "duplicates": duplicates, "linked": linked}
