"""Build immutable news snapshots without touching formal model features."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.news_feature_snapshots import SNAPSHOT_LABELS, SnapshotLabel, snapshot_cutoff
from scripts.news_feature_storage import store_feature_snapshot


def due_snapshot_labels(kickoff: datetime, now: datetime) -> list[SnapshotLabel]:
    return [label for label in SNAPSHOT_LABELS if snapshot_cutoff(kickoff, label) <= now]


def run(now: datetime | None = None) -> dict[str, Any]:
    run_at = now or datetime.now(UTC)
    created = 0
    considered = 0
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, kickoff_time AT TIME ZONE 'Asia/Shanghai'
            FROM official_matches
            WHERE official_match_code IS NOT NULL
              AND kickoff_time BETWEEN timezone('Asia/Shanghai', NOW()) - INTERVAL '3 hours'
                                   AND timezone('Asia/Shanghai', NOW()) + INTERVAL '36 hours'
            ORDER BY kickoff_time, id
            """
        )
        matches = cur.fetchall()
        for match_id, kickoff in matches:
            for label in due_snapshot_labels(kickoff, run_at):
                considered += 1
                created += int(
                    store_feature_snapshot(
                        conn,
                        match_id=int(match_id),
                        label=label,
                        cutoff=snapshot_cutoff(kickoff, label),
                    )
                )
    return {"status": "ok", "considered": considered, "created": created}


if __name__ == "__main__":
    print(run())
