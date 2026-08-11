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
                (SELECT MAX(captured_at) FROM news_articles_raw),
                EXISTS (
                    SELECT 1 FROM news_feature_release_settings
                    WHERE id = 1 AND mode = 'production'
                ),
                (SELECT COUNT(*) FROM news_article_screenings),
                (SELECT COUNT(*) FROM news_article_screenings WHERE screening_method = 'llm'),
                (SELECT COUNT(*) FROM news_model_invocations WHERE status = 'failed'),
                (SELECT COUNT(*) FROM news_article_screenings
                 WHERE accepted AND requires_review),
                (SELECT MAX(created_at) FROM news_model_invocations),
                EXISTS (
                    SELECT 1
                    FROM llm_agent_bindings binding
                    JOIN llm_provider_configs provider
                      ON provider.provider_code = binding.provider_code
                    WHERE binding.agent_code = 'news_extraction_agent'
                      AND binding.enabled
                      AND provider.enabled
                      AND provider.last_test_status = 'passed'
                )
            """
        )
        row = cur.fetchone() or (0, 0, 0, 0, None, False, 0, 0, 0, 0, None, False)
    return {
        "articleCount": int(row[0] or 0),
        "linkedMatchCount": int(row[1] or 0),
        "sourceCount": int(row[2] or 0),
        "healthySourceCount": int(row[3] or 0),
        "lastCapturedAt": _iso(row[4]),
        "productionFeatureEnabled": bool(row[5]),
        "screeningCount": int(row[6] or 0),
        "aiScreeningCount": int(row[7] or 0),
        "modelFailureCount": int(row[8] or 0),
        "pendingReviewCount": int(row[9] or 0),
        "lastModelInvocationAt": _iso(row[10]),
        "newsAgentReady": bool(row[11]),
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


def list_news_events(
    conn: Any,
    *,
    match_id: int | None = None,
    verification_status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if match_id is not None:
        filters.append("entity.match_id = %(match_id)s")
        params["match_id"] = match_id
    if verification_status:
        filters.append("event.verification_status = %(verification_status)s")
        params["verification_status"] = verification_status
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT event.id, event.event_type, event.direction, event.title, event.summary,
                   event.severity_score, event.confidence_score,
                   event.match_relevance_score, event.verification_status,
                   event.occurred_at, event.first_available_at,
                   event.extraction_method, event.extraction_version,
                   entity.match_id, match.official_match_code, match.league_name,
                   match.home_team_name, match.away_team_name,
                   COUNT(DISTINCT evidence.id) AS source_count
            FROM news_events event
            LEFT JOIN news_event_entities entity
                ON entity.event_id = event.id AND entity.match_id IS NOT NULL
            LEFT JOIN official_matches match ON match.id = entity.match_id
            LEFT JOIN news_event_evidence evidence ON evidence.event_id = event.id
            {where}
            GROUP BY event.id, entity.match_id, match.official_match_code, match.league_name,
                     match.home_team_name, match.away_team_name
            ORDER BY event.first_available_at DESC, event.id DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        rows = cur.fetchall()
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT event.id)
            FROM news_events event
            LEFT JOIN news_event_entities entity
                ON entity.event_id = event.id AND entity.match_id IS NOT NULL
            {where}
            """,
            params,
        )
        total_row = cur.fetchone()
    return [
        {
            "id": row[0],
            "eventType": row[1],
            "direction": row[2],
            "title": row[3],
            "summary": row[4],
            "severityScore": float(row[5]),
            "confidenceScore": float(row[6]),
            "matchRelevanceScore": float(row[7]),
            "verificationStatus": row[8],
            "occurredAt": _iso(row[9]),
            "firstAvailableAt": _iso(row[10]),
            "extractionMethod": row[11],
            "extractionVersion": row[12],
            "matchId": row[13],
            "officialMatchCode": row[14],
            "leagueName": row[15],
            "homeTeamName": row[16],
            "awayTeamName": row[17],
            "sourceCount": int(row[18] or 0),
        }
        for row in rows
    ], int(total_row[0] if total_row else 0)


def review_news_event(
    conn: Any,
    *,
    event_id: int,
    status: str,
    review_note: str | None,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE news_events
            SET verification_status = %s,
                verified_at = CASE WHEN %s = 'verified' THEN NOW() ELSE NULL END,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, verification_status
            """,
            (status, status, event_id),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("新闻事件不存在")
        cur.execute(
            """
            INSERT INTO news_event_reviews (event_id, action, review_note)
            VALUES (%s, %s, %s)
            """,
            (event_id, status, review_note),
        )
    conn.commit()
    return {"id": row[0], "verificationStatus": row[1], "reviewNote": review_note}


def set_news_source_enabled(conn: Any, *, source_id: int, enabled: bool) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE news_sources
            SET enabled = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING id, source_code, source_name, source_level, enabled,
                      last_success_at, last_error
            """,
            (enabled, source_id),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("新闻信源不存在")
    conn.commit()
    return {
        "id": row[0],
        "sourceCode": row[1],
        "sourceName": row[2],
        "sourceLevel": row[3],
        "enabled": bool(row[4]),
        "lastSuccessAt": _iso(row[5]),
        "lastError": row[6],
    }


def list_news_feature_snapshots(
    conn: Any,
    *,
    match_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if match_id is not None:
        filters.append("feature.match_id = %(match_id)s")
        params["match_id"] = match_id
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT snapshot.id, feature.match_id, match.official_match_code,
                   match.league_name, match.home_team_name, match.away_team_name,
                   feature.snapshot_label, snapshot.snapshot_cutoff,
                   feature.home_net_impact, feature.away_net_impact,
                   feature.verified_event_count, feature.pending_event_count,
                   feature.evidence_count, feature.coverage_score,
                   feature.confidence_score, feature.feature_version
            FROM match_news_features feature
            JOIN match_news_snapshots snapshot ON snapshot.id = feature.snapshot_id
            JOIN official_matches match ON match.id = feature.match_id
            {where}
            ORDER BY snapshot.snapshot_cutoff DESC, snapshot.id DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        rows = cur.fetchall()
        cur.execute(
            f"SELECT COUNT(*) FROM match_news_features feature {where}",
            params,
        )
        total_row = cur.fetchone()
    return [
        {
            "snapshotId": row[0],
            "matchId": row[1],
            "officialMatchCode": row[2],
            "leagueName": row[3],
            "homeTeamName": row[4],
            "awayTeamName": row[5],
            "snapshotLabel": row[6],
            "snapshotCutoff": _iso(row[7]),
            "homeNetImpact": float(row[8]),
            "awayNetImpact": float(row[9]),
            "verifiedEventCount": int(row[10]),
            "pendingEventCount": int(row[11]),
            "evidenceCount": int(row[12]),
            "coverageScore": float(row[13]),
            "confidenceScore": float(row[14]),
            "featureVersion": row[15],
        }
        for row in rows
    ], int(total_row[0] if total_row else 0)


def get_news_shadow_experiment(conn: Any) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*), AVG(baseline_brier), AVG(shadow_brier),
                   AVG(baseline_log_loss), AVG(shadow_log_loss)
            FROM news_shadow_evaluations
            """
        )
        summary = cur.fetchone() or (0, None, None, None, None)
        cur.execute(
            """
            SELECT model.model_name, model.version, shadow.shadow_version,
                   COUNT(evaluation.id), AVG(evaluation.baseline_brier),
                   AVG(evaluation.shadow_brier), AVG(evaluation.baseline_log_loss),
                   AVG(evaluation.shadow_log_loss)
            FROM news_shadow_predictions shadow
            JOIN model_versions model ON model.id = shadow.baseline_model_version_id
            LEFT JOIN news_shadow_evaluations evaluation
                ON evaluation.shadow_prediction_id = shadow.id
            GROUP BY model.model_name, model.version, shadow.shadow_version
            ORDER BY COUNT(evaluation.id) DESC, model.model_name
            """
        )
        model_rows = cur.fetchall()
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM news_feature_release_settings
                WHERE id = 1 AND mode = 'production'
            )
            """
        )
        production_row = cur.fetchone()

    def rounded(value: Any) -> float | None:
        return round(float(value), 6) if value is not None else None

    baseline_brier = rounded(summary[1])
    shadow_brier = rounded(summary[2])
    baseline_log_loss = rounded(summary[3])
    shadow_log_loss = rounded(summary[4])
    models = []
    for row in model_rows:
        model_baseline_brier = rounded(row[4])
        model_shadow_brier = rounded(row[5])
        models.append(
            {
                "modelName": row[0],
                "modelVersion": row[1],
                "shadowVersion": row[2],
                "sampleSize": int(row[3] or 0),
                "baselineBrier": model_baseline_brier,
                "shadowBrier": model_shadow_brier,
                "brierDelta": round(model_shadow_brier - model_baseline_brier, 6)
                if model_shadow_brier is not None and model_baseline_brier is not None
                else None,
                "baselineLogLoss": rounded(row[6]),
                "shadowLogLoss": rounded(row[7]),
            }
        )
    return {
        "sampleSize": int(summary[0] or 0),
        "baselineBrier": baseline_brier,
        "shadowBrier": shadow_brier,
        "brierDelta": round(shadow_brier - baseline_brier, 6)
        if shadow_brier is not None and baseline_brier is not None
        else None,
        "baselineLogLoss": baseline_log_loss,
        "shadowLogLoss": shadow_log_loss,
        "logLossDelta": round(shadow_log_loss - baseline_log_loss, 6)
        if shadow_log_loss is not None and baseline_log_loss is not None
        else None,
        "productionFeatureEnabled": bool(production_row and production_row[0]),
        "models": models,
    }
