"""供影子模型共享的官方赛前特征训练集。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from scripts.business_time import business_now_naive
from scripts.feature_schema import (
    COMPATIBLE_SNAPSHOT_VERSIONS,
    FEATURE_COLUMNS,
    numeric_feature_value,
)


def load_observed_feature_input(conn: Any, **contract: Any) -> dict:
    """Explicit exact-ID observation pilot; legacy training stays unreplayed."""
    from scripts.observed_feature_pipeline import load_observed_feature_input as load

    return load(conn, **contract)


def load_prediction_input_mode(conn: Any, **contract: Any) -> dict:
    """Explicit P105 mode selection on the same retained P104 batch."""
    from scripts.prediction_input_policy import load_prediction_input_mode as load

    return load(conn, **contract)


def complete_prediction_input_revision(conn: Any, claim: Any, **contract: Any) -> dict:
    """Explicit P105 retained input gate; no default model or ticket activation."""
    from scripts.prediction_input_revisions import complete_prediction_input_revision as complete

    return complete(conn, claim, **contract)


def load_prediction_input_revision(conn: Any, revision_id: int) -> dict | None:
    """Current DB validation for the exact retained input decision."""
    from scripts.prediction_input_revisions import load_prediction_input_revision as load

    return load(conn, revision_id)


def load_settled_pre_kickoff_dataset(
    conn: Any,
    *,
    cutoff_at: datetime | None = None,
    max_matches: int = 5000,
) -> tuple[np.ndarray, np.ndarray, list[str]] | None:
    """Select the latest eligible matches, then return them chronologically.

    The cutoff is a naive business-local timestamp, matching the legacy SQL
    columns. Unknown result publication times cannot establish label readiness.
    This selects retained snapshots; it does not reconstruct historical facts.
    """
    if type(max_matches) is not int or not 1 <= max_matches <= 5000:
        raise ValueError("max_matches must be an integer between 1 and 5000")
    cutoff = business_now_naive() if cutoff_at is None else cutoff_at
    if not isinstance(cutoff, datetime) or cutoff.tzinfo is not None:
        raise ValueError("cutoff_at must be a timezone-naive business datetime")
    columns = ", ".join(f"fs.{column}" for column in FEATURE_COLUMNS)
    output_columns = ", ".join(FEATURE_COLUMNS)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH latest_feature_snapshots AS (
                SELECT DISTINCT ON (fs.match_id) fs.*
                FROM match_feature_snapshots fs
                JOIN official_matches m ON m.id = fs.match_id
                WHERE fs.snapshot_time < m.kickoff_time
                  AND fs.feature_version IN %(feature_versions)s
                ORDER BY fs.match_id, fs.snapshot_time DESC, fs.id DESC
            ), recent_matches AS (
            SELECT m.id AS match_id, m.kickoff_time, {columns},
                   CASE
                       WHEN r.full_home_goals > r.full_away_goals THEN 2
                       WHEN r.full_home_goals = r.full_away_goals THEN 1
                       ELSE 0
                   END AS label
            FROM latest_feature_snapshots fs
            JOIN official_matches m ON m.id = fs.match_id
            JOIN official_results r ON r.match_id = fs.match_id
            WHERE r.result_status IN ('final', 'confirmed')
              AND r.full_home_goals IS NOT NULL AND r.full_home_goals >= 0
              AND r.full_away_goals IS NOT NULL AND r.full_away_goals >= 0
              AND m.kickoff_time < %(cutoff_at)s
              AND r.official_publish_time < %(cutoff_at)s
            ORDER BY m.kickoff_time DESC, fs.match_id DESC
            LIMIT %(max_matches)s
            )
            SELECT kickoff_time, {output_columns}, label
            FROM recent_matches
            ORDER BY kickoff_time ASC, match_id ASC
            """,
            {
                "feature_versions": COMPATIBLE_SNAPSHOT_VERSIONS,
                "cutoff_at": cutoff,
                "max_matches": max_matches,
            },
        )
        rows = cur.fetchall()
    if not rows:
        return None

    feature_count = len(FEATURE_COLUMNS)
    features = np.array(
        [[numeric_feature_value(value) for value in row[1 : feature_count + 1]] for row in rows],
        dtype=np.float64,
    )
    labels = np.array([int(row[-1]) for row in rows], dtype=np.int64)
    dates = [str(row[0]) for row in rows]
    return features, labels, dates
