"""Read prediction vectors atomically, with an explicit legacy fallback."""

from __future__ import annotations

from datetime import UTC
from typing import Any

from scripts.model_prediction_run_identity import (
    verify_prediction_artifact_binding,
    verify_prediction_group_output_manifest,
    verify_prediction_run_manifest,
    verify_prediction_run_output_manifest,
)

GROUP_COLUMNS = """g.id, g.run_id, g.match_id, g.model_version_id, g.play_type,
                      g.market_variant, g.predict_time, g.expected_options,
                      g.probability_vector, g.output_sha256, g.provenance_status,
                      g.output_manifest, g.output_manifest_canonical,
                      r.run_status, r.provenance_status,
                      r.run_manifest, r.run_manifest_sha256,
                      r.model_manifest, r.model_manifest_sha256,
                      r.input_manifest, r.input_manifest_sha256,
                      r.output_summary, r.output_manifest,
                      r.output_manifest_sha256, r.output_manifest_canonical,
                      (SELECT COALESCE(
                           jsonb_agg(g2.output_sha256 ORDER BY g2.match_id,
                                     g2.model_version_id, g2.play_type,
                                     g2.market_variant, g2.id), '[]'::jsonb)
                       FROM model_prediction_groups g2
                       WHERE g2.run_id=r.id AND g2.group_status='complete')
        """


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
            f"""SELECT {GROUP_COLUMNS}
               FROM model_prediction_groups g
               JOIN model_prediction_runs r ON r.id=g.run_id
               WHERE g.match_id = %s AND g.model_version_id = %s AND g.play_type = %s
                 AND g.group_status = 'complete' {variant_filter}
                 AND r.run_status IN ('completed','partial')
               ORDER BY g.predict_time DESC, g.created_at DESC, g.id DESC
               LIMIT 1""",
            params,
        )
        group = cur.fetchone()

    if group is not None:
        return _materialize_group(conn, group)

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


def _materialize_group(conn: Any, group: tuple, rows: list | None = None) -> dict[str, Any]:
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
        output_manifest,
        output_manifest_canonical,
        run_status,
        run_provenance,
        run_manifest,
        run_manifest_sha256,
        model_manifest,
        model_manifest_sha256,
        input_manifest,
        input_manifest_sha256,
        output_summary,
        run_output_manifest,
        run_output_manifest_sha256,
        run_output_manifest_canonical,
        run_output_hashes,
    ) = group
    try:
        verify_prediction_run_manifest(
            run_manifest=run_manifest,
            run_manifest_sha256=run_manifest_sha256,
            model_manifest=model_manifest,
            model_manifest_sha256=model_manifest_sha256,
            input_manifest=input_manifest,
            input_manifest_sha256=input_manifest_sha256,
        )
        verify_prediction_run_output_manifest(
            output_manifest=run_output_manifest,
            output_manifest_sha256=run_output_manifest_sha256,
            output_manifest_canonical=run_output_manifest_canonical,
            output_summary=output_summary,
            expected_group_hashes=run_output_hashes,
            required_group_sha256=digest,
        )
        verify_prediction_group_output_manifest(
            output_manifest=output_manifest,
            output_sha256=digest,
            output_manifest_canonical=output_manifest_canonical,
            match_id=int(mid),
            model_version_id=int(model_id),
            play_type=str(group_play_type),
            market_variant=str(variant or ""),
            predict_time=predict_time,
            expected_options=expected,
            probability_vector=vector,
        )
        if provenance == "complete" and run_provenance == "complete":
            verify_prediction_artifact_binding(
                model_manifest,
                output_manifest.get("artifact_identity"),
                model_version_id=int(model_id),
            )
        elif provenance == "complete" or run_provenance == "complete":
            raise ValueError("prediction group and run provenance statuses disagree")
    except (TypeError, ValueError) as exc:
        return {
            "status": "invalid_integrity",
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
            "run_provenance_status": run_provenance,
            "integrity_error": str(exc),
            "options": [],
        }
    if rows is None:
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
    loaded_vector = {
        item["option_code"]: item["model_probability"]
        for item in options
        if item["model_probability"] is not None
    }
    status = "complete"
    if sorted(item["option_code"] for item in options) != sorted(expected):
        status = "incomplete_group"
    elif loaded_vector != dict(vector):
        status = "invalid_integrity"
    if status != "complete":
        options = []
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
        "run_provenance_status": run_provenance,
        **(
            {"integrity_error": "stored options disagree with the hashed probability vector"}
            if status == "invalid_integrity"
            else {}
        ),
        "options": options,
    }


def load_pool_prediction_groups(
    conn: Any, *, cutoffs: dict[int, Any], historical: bool = False
) -> list[dict[str, Any]]:
    """Batch as-of SPF groups by logical model. Legacy remains research-only.

    Audit timestamps are timestamptz; prediction/schedule timestamps are local
    Shanghai wall times. Select within cutoff before ranking. A bad newest group
    is returned as bad, never replaced by an older good group.
    """
    if not cutoffs:
        return []
    ids = sorted(cutoffs)
    with conn.cursor() as cur:
        cur.execute(
            f"""WITH limits AS (
                SELECT * FROM unnest(%s::bigint[], %s::timestamptz[]) AS x(match_id, cutoff)
            ), version_candidates AS (
                SELECT lim.match_id,mv.model_name,g.id,g.predict_time,g.created_at
                FROM limits lim CROSS JOIN model_versions mv
                JOIN LATERAL (
                    SELECT g.id,g.predict_time,g.created_at
                    FROM model_prediction_groups g JOIN model_prediction_runs r ON r.id=g.run_id
                    WHERE g.match_id=lim.match_id AND g.model_version_id=mv.id
                      AND g.play_type='spf' AND g.market_variant='' AND g.group_status='complete'
                      AND r.run_status IN ('completed','partial')
                      AND g.predict_time < (lim.cutoff AT TIME ZONE 'Asia/Shanghai')
                      AND g.created_at < lim.cutoff AND g.completed_at < lim.cutoff
                      AND r.created_at < lim.cutoff AND r.finished_at < lim.cutoff
                    ORDER BY g.predict_time DESC,g.created_at DESC,g.id DESC LIMIT 1
                ) g ON true
                WHERE (%s OR mv.is_active=true)
            ), chosen AS (
                SELECT DISTINCT ON (match_id,model_name) id FROM version_candidates
                ORDER BY match_id,model_name,predict_time DESC,created_at DESC,id DESC
            ) SELECT {GROUP_COLUMNS}, mv.model_name
              FROM chosen JOIN model_prediction_groups g ON g.id=chosen.id
              JOIN model_prediction_runs r ON r.id=g.run_id
              JOIN model_versions mv ON mv.id=g.model_version_id
              ORDER BY g.match_id, mv.model_name""",
            (ids, [cutoffs[i] for i in ids], historical),
        )
        groups = cur.fetchall()
        if not groups:
            return []
        cur.execute(
            """SELECT om.group_id, mp.id, om.option_code, mp.model_probability,
                      mp.market_probability, mp.odds_snapshot_id, mp.feature_snapshot_id,
                      mp.predict_time, mp.play_type, mp.validation_status,
                      mp.uncertainty_reason, mp.created_at
               FROM model_prediction_group_options om
               JOIN model_predictions mp ON mp.id=om.prediction_id
               WHERE om.group_id=ANY(%s::uuid[]) ORDER BY om.group_id, om.ordinal""",
            ([g[0] for g in groups],),
        )
        option_rows = cur.fetchall()
    by_group: dict[Any, list] = {}
    for row in option_rows:
        by_group.setdefault(row[0], []).append(row[1:])
    loaded = []
    for row in groups:
        options = by_group.get(row[0], [])
        group = _materialize_group(conn, row[:-1], [item[:8] for item in options])
        group["model_name"] = row[-1]
        group["manifest_hashes"] = {
            "run": row[16],
            "model": row[18],
            "input": row[20],
            "output": row[23],
        }
        group["eligible"] = bool(options) and all(
            o[8] == "valid"
            and isinstance(o[9], dict)
            and o[9].get("model_independent") is True
            and o[10] is not None
            and o[10].replace(tzinfo=UTC) < cutoffs[group["match_id"]]
            for o in options
        )
        loaded.append(group)
    return loaded
