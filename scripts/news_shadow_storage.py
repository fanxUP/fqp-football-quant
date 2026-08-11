"""Persistence for isolated news shadow predictions and evaluations."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from psycopg2.extras import Json

from scripts.news_shadow_model import (
    MAX_PROBABILITY_SHIFT,
    SHADOW_VERSION,
    adjust_probabilities,
    score_prediction,
)


def generate_shadow_predictions(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH latest_feature AS (
                SELECT DISTINCT ON (feature.match_id)
                       feature.match_id, feature.snapshot_id,
                       feature.home_net_impact, feature.away_net_impact,
                       snapshot.snapshot_cutoff
                FROM match_news_features feature
                JOIN match_news_snapshots snapshot ON snapshot.id = feature.snapshot_id
                JOIN official_matches match ON match.id = feature.match_id
                WHERE feature.snapshot_label = 'T45M'
                  AND match.official_match_code IS NOT NULL
                ORDER BY feature.match_id, snapshot.snapshot_cutoff DESC, snapshot.id DESC
            ), latest_prediction AS (
                SELECT DISTINCT ON (
                           prediction.match_id, prediction.model_version_id,
                           prediction.option_code
                       )
                       prediction.match_id, prediction.model_version_id,
                       prediction.option_code, prediction.model_probability,
                       prediction.predict_time, feature.snapshot_id,
                       feature.home_net_impact, feature.away_net_impact
                FROM model_predictions prediction
                JOIN model_versions model ON model.id = prediction.model_version_id
                JOIN latest_feature feature ON feature.match_id = prediction.match_id
                WHERE prediction.play_type = 'spf'
                  AND prediction.option_code IN ('3', '1', '0')
                  AND prediction.validation_status = 'valid'
                  AND model.is_active = true
                  AND prediction.predict_time <= feature.snapshot_cutoff AT TIME ZONE 'Asia/Shanghai'
                ORDER BY prediction.match_id, prediction.model_version_id,
                         prediction.option_code, prediction.predict_time DESC, prediction.id DESC
            )
            SELECT match_id, model_version_id, option_code, model_probability,
                   predict_time, snapshot_id, home_net_impact, away_net_impact
            FROM latest_prediction
            ORDER BY match_id, model_version_id, option_code
            """
        )
        rows = cur.fetchall()

    grouped: defaultdict[tuple[int, int, int], list[tuple[Any, ...]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row[0]), int(row[1]), int(row[5]))].append(row)

    created = 0
    for (match_id, model_version_id, snapshot_id), group in grouped.items():
        baseline = {str(row[2]): float(row[3]) for row in group}
        if set(baseline) != {"3", "1", "0"}:
            continue
        home_impact = float(group[0][6] or 0)
        away_impact = float(group[0][7] or 0)
        shadow = adjust_probabilities(baseline, home_impact, away_impact)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_shadow_predictions (
                    match_id, snapshot_id, baseline_model_version_id,
                    baseline_predict_time, baseline_probabilities, shadow_probabilities,
                    home_news_impact, away_news_impact, max_probability_shift, shadow_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    match_id, snapshot_id, baseline_model_version_id, shadow_version
                ) DO NOTHING
                RETURNING id
                """,
                (
                    match_id,
                    snapshot_id,
                    model_version_id,
                    group[0][4],
                    Json(baseline),
                    Json(shadow),
                    home_impact,
                    away_impact,
                    MAX_PROBABILITY_SHIFT,
                    SHADOW_VERSION,
                ),
            )
            created += int(cur.fetchone() is not None)
    conn.commit()
    return created


def evaluate_shadow_predictions(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT shadow.id, shadow.match_id, shadow.baseline_probabilities,
                   shadow.shadow_probabilities, result.full_home_goals,
                   result.full_away_goals
            FROM news_shadow_predictions shadow
            JOIN official_results result ON result.match_id = shadow.match_id
            WHERE result.result_status = 'confirmed'
              AND NOT EXISTS (
                  SELECT 1 FROM news_shadow_evaluations evaluation
                  WHERE evaluation.shadow_prediction_id = shadow.id
              )
            ORDER BY shadow.id
            """
        )
        rows = cur.fetchall()

    created = 0
    for row in rows:
        home_goals, away_goals = int(row[4]), int(row[5])
        actual = "3" if home_goals > away_goals else "1" if home_goals == away_goals else "0"
        baseline = score_prediction(row[2], actual)
        shadow = score_prediction(row[3], actual)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_shadow_evaluations (
                    shadow_prediction_id, match_id, actual_option,
                    baseline_brier, shadow_brier, baseline_log_loss, shadow_log_loss
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (shadow_prediction_id) DO NOTHING
                RETURNING id
                """,
                (
                    row[0],
                    row[1],
                    actual,
                    baseline["brier"],
                    shadow["brier"],
                    baseline["logLoss"],
                    shadow["logLoss"],
                ),
            )
            created += int(cur.fetchone() is not None)
    conn.commit()
    return created
