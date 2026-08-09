"""供影子模型共享的官方赛前特征训练集。"""

from __future__ import annotations

from typing import Any

import numpy as np

from scripts.feature_importance import FEATURE_COLUMNS


def load_settled_pre_kickoff_dataset(
    conn: Any,
) -> tuple[np.ndarray, np.ndarray, list[str]] | None:
    """Load chronological, official and strictly pre-kickoff feature rows only."""
    columns = ", ".join(f"fs.{column}" for column in FEATURE_COLUMNS)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH latest_feature_snapshots AS (
                SELECT DISTINCT ON (fs.match_id) fs.*
                FROM match_feature_snapshots fs
                JOIN official_matches m ON m.id = fs.match_id
                WHERE fs.snapshot_time < m.kickoff_time
                ORDER BY fs.match_id, fs.snapshot_time DESC, fs.id DESC
            )
            SELECT m.kickoff_time, {columns},
                   CASE
                       WHEN r.full_home_goals > r.full_away_goals THEN 2
                       WHEN r.full_home_goals = r.full_away_goals THEN 1
                       ELSE 0
                   END AS label
            FROM latest_feature_snapshots fs
            JOIN official_matches m ON m.id = fs.match_id
            JOIN official_results r ON r.match_id = fs.match_id
            WHERE r.result_status IN ('final', 'confirmed')
            ORDER BY m.kickoff_time ASC, fs.match_id ASC
            LIMIT 5000
            """
        )
        rows = cur.fetchall()
    if not rows:
        return None

    feature_count = len(FEATURE_COLUMNS)
    features = np.array(
        [
            [float(value) if value is not None else np.nan for value in row[1 : feature_count + 1]]
            for row in rows
        ],
        dtype=np.float64,
    )
    labels = np.array([int(row[-1]) for row in rows], dtype=np.int64)
    dates = [str(row[0]) for row in rows]
    return features, labels, dates
