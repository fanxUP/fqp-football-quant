"""Immutable storage for point-in-time News Intelligence feature snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from psycopg2.extras import Json

from scripts.news_feature_snapshots import FEATURE_VERSION, SnapshotLabel, build_feature_vector


def load_snapshot_events(
    conn: Any,
    *,
    match_id: int,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    """Read only evidence verifiably available by the requested cutoff."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT event.id, event.event_type, event.direction, event.title,
                   event.summary, event.severity_score, event.confidence_score,
                   CASE
                       WHEN event.verification_status = 'verified'
                            AND event.verified_at <= %s THEN 'verified'
                       WHEN event.verification_status = 'rejected'
                            AND EXISTS (
                                SELECT 1 FROM news_event_reviews review
                                WHERE review.event_id = event.id
                                  AND review.action = 'rejected'
                                  AND review.created_at <= %s
                            ) THEN 'rejected'
                       ELSE 'pending'
                   END AS point_in_time_status,
                   event.first_available_at,
                   entity.entity_role, COUNT(DISTINCT evidence.id)
            FROM news_events event
            JOIN news_event_entities entity ON entity.event_id = event.id
            JOIN news_event_evidence evidence ON evidence.event_id = event.id
            WHERE entity.match_id = %s
              AND event.first_available_at <= %s
              AND evidence.available_at <= %s
            GROUP BY event.id, entity.entity_role
            ORDER BY event.first_available_at, event.id
            """,
            (cutoff, cutoff, match_id, cutoff, cutoff),
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "eventType": row[1],
            "direction": row[2],
            "title": row[3],
            "summary": row[4],
            "severityScore": float(row[5]),
            "confidenceScore": float(row[6]),
            "verificationStatus": row[7],
            "firstAvailableAt": row[8].isoformat(),
            "entityRole": row[9],
            "sourceCount": int(row[10] or 0),
        }
        for row in rows
    ]


def store_feature_snapshot(
    conn: Any,
    *,
    match_id: int,
    label: SnapshotLabel,
    cutoff: datetime,
) -> bool:
    events = load_snapshot_events(conn, match_id=match_id, cutoff=cutoff)
    vector = build_feature_vector(events)
    serialized = json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(serialized.encode()).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO match_news_snapshots (
                match_id, snapshot_label, snapshot_cutoff, event_payload,
                event_count, evidence_count, checksum, feature_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_id, snapshot_label, feature_version) DO NOTHING
            RETURNING id
            """,
            (
                match_id,
                label,
                cutoff,
                Json(events),
                len(events),
                vector["evidenceCount"],
                checksum,
                FEATURE_VERSION,
            ),
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return False
        cur.execute(
            """
            INSERT INTO match_news_features (
                snapshot_id, match_id, snapshot_label,
                home_positive_impact, home_negative_impact,
                away_positive_impact, away_negative_impact,
                home_net_impact, away_net_impact,
                verified_event_count, pending_event_count, evidence_count,
                coverage_score, confidence_score, feature_vector, feature_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                row[0],
                match_id,
                label,
                vector["homePositiveImpact"],
                vector["homeNegativeImpact"],
                vector["awayPositiveImpact"],
                vector["awayNegativeImpact"],
                vector["homeNetImpact"],
                vector["awayNetImpact"],
                vector["verifiedEventCount"],
                vector["pendingEventCount"],
                vector["evidenceCount"],
                vector["coverageScore"],
                vector["confidenceScore"],
                Json(vector),
                FEATURE_VERSION,
            ),
        )
    conn.commit()
    return True
