"""Append-only storage for normalized news discovery candidates."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from psycopg2.extras import Json

from scripts.news_intelligence_clients import NewsArticleCandidate
from scripts.news_source_policy import load_news_source_policies, resolve_source_policy


def load_news_watch_matches(conn: Any, limit: int = 80) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT match.id, match.official_match_code,
                   match.home_team_name, match.away_team_name, match.kickoff_time,
                   ARRAY_REMOVE(
                       ARRAY[match.home_team_name, home_team.team_name_en]
                       || COALESCE(home_aliases.aliases, ARRAY[]::text[]), NULL
                   ) AS home_search_terms,
                   ARRAY_REMOVE(
                       ARRAY[match.away_team_name, away_team.team_name_en]
                       || COALESCE(away_aliases.aliases, ARRAY[]::text[]), NULL
                   ) AS away_search_terms
            FROM official_matches match
            LEFT JOIN LATERAL (
                SELECT alias.team_id
                FROM team_aliases alias
                WHERE alias.alias_name = match.home_team_name
                ORDER BY (alias.source_name = 'sporttery') DESC, alias.is_verified DESC, alias.id
                LIMIT 1
            ) home_identity ON TRUE
            LEFT JOIN teams home_team ON home_team.id = home_identity.team_id
            LEFT JOIN LATERAL (
                SELECT ARRAY_AGG(DISTINCT alias.alias_name ORDER BY alias.alias_name) AS aliases
                FROM team_aliases alias
                WHERE alias.team_id = home_identity.team_id AND alias.is_verified
            ) home_aliases ON TRUE
            LEFT JOIN LATERAL (
                SELECT alias.team_id
                FROM team_aliases alias
                WHERE alias.alias_name = match.away_team_name
                ORDER BY (alias.source_name = 'sporttery') DESC, alias.is_verified DESC, alias.id
                LIMIT 1
            ) away_identity ON TRUE
            LEFT JOIN teams away_team ON away_team.id = away_identity.team_id
            LEFT JOIN LATERAL (
                SELECT ARRAY_AGG(DISTINCT alias.alias_name ORDER BY alias.alias_name) AS aliases
                FROM team_aliases alias
                WHERE alias.team_id = away_identity.team_id AND alias.is_verified
            ) away_aliases ON TRUE
            WHERE match.official_match_code IS NOT NULL
              AND match.kickoff_time BETWEEN timezone('Asia/Shanghai', NOW())
                                         AND timezone('Asia/Shanghai', NOW()) + INTERVAL '36 hours'
            ORDER BY match.kickoff_time, match.id
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
            "home_search_terms": list(dict.fromkeys(row[5] or [row[2]])),
            "away_search_terms": list(dict.fromkeys(row[6] or [row[3]])),
        }
        for row in rows
    ]


def match_candidate_to_official_matches(
    candidate: NewsArticleCandidate,
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text = f"{candidate.title}\n{candidate.description}".casefold()
    linked: list[dict[str, Any]] = []
    for match in matches:
        terms = [
            *match.get("home_search_terms", [match.get("home_team_name")]),
            *match.get("away_search_terms", [match.get("away_team_name")]),
        ]
        if any(str(term or "").casefold() in text for term in terms if str(term or "").strip()):
            linked.append(match)
    return linked


def filter_match_relevant_candidates(
    candidates: list[NewsArticleCandidate],
    matches: list[dict[str, Any]],
) -> tuple[list[NewsArticleCandidate], int]:
    """Reject aggregator body-only matches that visible metadata cannot link."""
    accepted = [
        candidate
        for candidate in candidates
        if match_candidate_to_official_matches(candidate, matches)
    ]
    return accepted, len(candidates) - len(accepted)


def load_provider_request_counts(conn: Any, *, day_start: datetime) -> dict[str, int]:
    """Count persisted provider requests since the UTC free-tier reset."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT provider_code, COUNT(*)
            FROM news_ingestion_runs
            WHERE started_at >= %s
            GROUP BY provider_code
            """,
            (day_start,),
        )
        rows = cur.fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def record_news_ingestion_request(conn: Any, payload: dict[str, Any]) -> None:
    """Persist one external request so restarts cannot reset daily usage."""
    params = {**payload, "cursor_state": Json(payload.get("cursor_state", {}))}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO news_ingestion_runs (
                provider_code, started_at, finished_at, status,
                requested_count, inserted_count, duplicate_count,
                error_message, cursor_state
            )
            VALUES (%(provider_code)s, %(started_at)s, %(finished_at)s, %(status)s,
                    %(requested_count)s, %(inserted_count)s, %(duplicate_count)s,
                    %(error_message)s, %(cursor_state)s)
            """,
            params,
        )
    conn.commit()


def store_news_candidates(
    conn: Any,
    candidates: list[NewsArticleCandidate],
    matches: list[dict[str, Any]],
    *,
    observed_at: datetime,
) -> dict[str, int]:
    policies = load_news_source_policies(conn)
    inserted = 0
    duplicates = 0
    linked = 0
    filtered = 0
    for candidate in candidates:
        policy = resolve_source_policy(candidate.source_domain, policies)
        if not policy.enabled:
            filtered += 1
            continue
        source_code = (
            "publisher:" + hashlib.sha256(candidate.source_domain.encode()).hexdigest()[:24]
        )
        content_hash = hashlib.sha256(
            f"{candidate.title}\n{candidate.description}".encode()
        ).hexdigest()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_sources (
                    source_code, source_name, publisher_domain, source_level, source_type,
                    default_language, enabled, last_success_at, last_error
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NULL)
                ON CONFLICT (source_code) DO UPDATE SET
                    source_name = EXCLUDED.source_name,
                    source_level = EXCLUDED.source_level,
                    source_type = EXCLUDED.source_type,
                    default_language = EXCLUDED.default_language,
                    enabled = EXCLUDED.enabled,
                    last_success_at = NOW(), last_error = NULL, updated_at = NOW()
                RETURNING id
                """,
                (
                    source_code,
                    policy.display_name or candidate.source_name,
                    candidate.source_domain,
                    policy.source_level,
                    policy.source_type,
                    policy.default_language or candidate.language,
                    policy.enabled,
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
            for match in match_candidate_to_official_matches(candidate, matches):
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
    return {
        "inserted": inserted,
        "duplicates": duplicates,
        "linked": linked,
        "filtered": filtered,
    }
