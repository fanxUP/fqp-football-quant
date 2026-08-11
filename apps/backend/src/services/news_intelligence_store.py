"""Read models for the isolated News Intelligence module."""

from __future__ import annotations

from typing import Any


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def get_news_overview(conn: Any) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM news_articles_raw),
                (SELECT COUNT(DISTINCT match_id) FROM news_article_matches),
                (SELECT COUNT(*) FROM news_sources),
                (SELECT COUNT(*) FROM news_sources WHERE enabled AND last_error IS NULL),
                (SELECT MAX(captured_at) FROM news_articles_raw)
            """
        )
        row = cur.fetchone() or (0, 0, 0, 0, None)
    return {
        "articleCount": int(row[0] or 0),
        "linkedMatchCount": int(row[1] or 0),
        "sourceCount": int(row[2] or 0),
        "healthySourceCount": int(row[3] or 0),
        "lastCapturedAt": _iso(row[4]),
        "productionFeatureEnabled": False,
    }


def list_news_sources(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, source_code, source_name, publisher_domain, source_level,
                   source_type, default_language, enabled, last_success_at, last_error
            FROM news_sources
            ORDER BY source_level, source_name, id
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "sourceCode": row[1],
            "sourceName": row[2],
            "publisherDomain": row[3],
            "sourceLevel": row[4],
            "sourceType": row[5],
            "defaultLanguage": row[6],
            "enabled": bool(row[7]),
            "lastSuccessAt": _iso(row[8]),
            "lastError": row[9],
        }
        for row in rows
    ]


def list_news_articles(
    conn: Any,
    *,
    match_id: int | None = None,
    source_level: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if match_id is not None:
        filters.append("link.match_id = %(match_id)s")
        params["match_id"] = match_id
    if source_level:
        filters.append("source.source_level = %(source_level)s")
        params["source_level"] = source_level
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT article.id, link.match_id, match.official_match_code,
                   match.league_name, match.home_team_name, match.away_team_name,
                   source.source_name, source.source_level, source.source_type,
                   article.title, article.description, article.canonical_url,
                   article.language, article.published_at, article.observed_at,
                   article.captured_at, article.available_at
            FROM news_articles_raw article
            JOIN news_sources source ON source.id = article.source_id
            LEFT JOIN news_article_matches link ON link.article_id = article.id
            LEFT JOIN official_matches match ON match.id = link.match_id
            {where}
            ORDER BY article.available_at DESC, article.id DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        rows = cur.fetchall()
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM news_articles_raw article
            JOIN news_sources source ON source.id = article.source_id
            LEFT JOIN news_article_matches link ON link.article_id = article.id
            {where}
            """,
            params,
        )
        total_row = cur.fetchone()
    items = [
        {
            "id": row[0],
            "matchId": row[1],
            "officialMatchCode": row[2],
            "leagueName": row[3],
            "homeTeamName": row[4],
            "awayTeamName": row[5],
            "sourceName": row[6],
            "sourceLevel": row[7],
            "sourceType": row[8],
            "title": row[9],
            "description": row[10],
            "canonicalUrl": row[11],
            "language": row[12],
            "publishedAt": _iso(row[13]),
            "observedAt": _iso(row[14]),
            "capturedAt": _iso(row[15]),
            "availableAt": _iso(row[16]),
        }
        for row in rows
    ]
    return items, int(total_row[0] if total_row else 0)
