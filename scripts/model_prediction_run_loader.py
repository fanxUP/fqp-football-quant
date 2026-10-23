"""Read prediction vectors atomically, with an explicit legacy fallback."""

from __future__ import annotations

from typing import Any


def load_latest_prediction_group(
    conn: Any,
    *,
    match_id: int,
    model_version_id: int,
    play_type: str,
    market_variant: str | None = None,
) -> dict[str, Any] | None:
    """Return all outcomes from one latest complete group, never a mixed vector.

    A legacy vector is returned only when no published run-aware group exists for
    the same match/model/play key. If a published group is structurally incomplete,
    the result is marked incomplete rather than silently falling back.
    """
    variant_filter = "AND market_variant = %s" if market_variant is not None else ""
    params: tuple[Any, ...] = (match_id, model_version_id, play_type)
    if market_variant is not None:
        params += (market_variant,)
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT id, run_id, match_id, model_version_id, play_type,
                      market_variant, predict_time, expected_options,
                      probability_vector, output_sha256, provenance_status
               FROM model_prediction_groups
               WHERE match_id = %s AND model_version_id = %s AND play_type = %s
                 AND group_status = 'complete' {variant_filter}
                 AND EXISTS (
                     SELECT 1 FROM model_prediction_runs r
                     WHERE r.id=model_prediction_groups.run_id
                       AND r.run_status IN ('completed','partial')
                 )
               ORDER BY predict_time DESC, created_at DESC, id DESC
               LIMIT 1""",
            params,
        )
        group = cur.fetchone()

    if group is not None:
        (
            group_id,
            run_id,
            mid,
            model_id,
            group_play_type,
            variant,
            predict_time,
            expected,
            vector,
            digest,
            provenance,
        ) = group
        with conn.cursor() as cur:
            cur.execute(
                """SELECT mp.id, option_map.option_code, mp.model_probability,
                          mp.market_probability, mp.odds_snapshot_id, mp.feature_snapshot_id,
                          mp.predict_time, mp.play_type
                   FROM model_prediction_group_options option_map
                   JOIN model_predictions mp ON mp.id=option_map.prediction_id
                   WHERE option_map.group_id=%s
                   ORDER BY option_map.ordinal, option_map.option_code""",
                (group_id,),
            )
            rows = cur.fetchall()
        options = [
            {
                "prediction_id": row[0],
                "option_code": row[1],
                "model_probability": float(row[2]) if row[2] is not None else None,
                "market_probability": float(row[3]) if row[3] is not None else None,
                "odds_snapshot_id": row[4],
                "feature_snapshot_id": row[5],
                "predict_time": row[6],
                "play_type": row[7],
            }
            for row in rows
        ]
        status = (
            "complete"
            if sorted(item["option_code"] for item in options) == sorted(expected)
            else "incomplete_group"
        )
        return {
            "status": status,
            "group_id": group_id,
            "run_id": run_id,
            "match_id": mid,
            "model_version_id": model_id,
            "play_type": group_play_type,
            "market_variant": variant,
            "predict_time": predict_time,
            "expected_options": list(expected),
            "probability_vector": dict(vector),
            "output_sha256": digest,
            "provenance_status": provenance,
            "options": options,
        }

    if market_variant is not None:
        return None

    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (mp.option_code)
                      mp.id, mp.option_code, mp.model_probability, mp.market_probability,
                      mp.odds_snapshot_id, mp.feature_snapshot_id, mp.predict_time, mp.play_type
               FROM model_predictions mp
               WHERE mp.match_id=%s AND mp.model_version_id=%s AND mp.play_type=%s
                 AND NOT EXISTS (
                     SELECT 1 FROM model_prediction_group_options option_map
                     WHERE option_map.prediction_id=mp.id
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM model_prediction_groups g
                     JOIN model_prediction_runs r ON r.id=g.run_id
                     WHERE g.match_id=mp.match_id
                       AND g.model_version_id=mp.model_version_id
                       AND g.play_type=mp.play_type AND g.group_status='complete'
                       AND r.run_status IN ('completed','partial')
                 )
               ORDER BY mp.option_code, mp.predict_time DESC, mp.id DESC""",
            (match_id, model_version_id, play_type),
        )
        rows = cur.fetchall()
    if not rows:
        return None
    return {
        "status": "legacy-unbound",
        "group_id": None,
        "run_id": None,
        "match_id": match_id,
        "model_version_id": model_version_id,
        "play_type": play_type,
        "market_variant": "",
        "predict_time": max(row[6] for row in rows),
        "expected_options": [row[1] for row in rows],
        "probability_vector": {row[1]: float(row[2]) for row in rows if row[2] is not None},
        "provenance_status": "incomplete",
        "options": [
            {
                "prediction_id": row[0],
                "option_code": row[1],
                "model_probability": float(row[2]) if row[2] is not None else None,
                "market_probability": float(row[3]) if row[3] is not None else None,
                "odds_snapshot_id": row[4],
                "feature_snapshot_id": row[5],
                "predict_time": row[6],
                "play_type": row[7],
            }
            for row in rows
        ],
    }
