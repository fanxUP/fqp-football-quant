"""Transactional persistence for complete prediction runs and output groups."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from psycopg2.extras import Json

from scripts.model_prediction_run_identity import content_sha256
from scripts.model_storage import store_model_prediction


def _uuid(value: uuid.UUID | str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("valid prediction run UUID required") from exc


def _expected_options(metadata: Mapping[str, Any]) -> list[str]:
    raw_options = metadata.get("expected_options")
    if not isinstance(raw_options, (list, tuple)) or not raw_options:
        raise ValueError("expected options must be a non-empty sequence")
    options = [str(value) for value in raw_options]
    if len(set(options)) != len(options):
        raise ValueError("expected options must be unique")
    return sorted(options)


def _run_manifest(
    release_id: str,
    code_fingerprint: Mapping[str, Any],
    model_manifest: Sequence[Mapping[str, Any]],
    input_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    models = sorted(
        (dict(item) for item in model_manifest),
        key=lambda item: (str(item.get("model_name", "")), int(item.get("model_version_id", 0))),
    )
    inputs = dict(input_manifest)
    if isinstance(inputs.get("match_ids"), list):
        inputs["match_ids"] = sorted(set(inputs["match_ids"]))
    if isinstance(inputs.get("markets"), list):
        inputs["markets"] = sorted(inputs["markets"], key=lambda item: (item[0], item[1]))
    payload = {
        "schema_version": "fqp.model-prediction-run/v1",
        "release_id": release_id,
        "source_fingerprint": code_fingerprint.get("sha256"),
        "source_files": code_fingerprint.get("files", {}),
        "model_manifest": models,
        "input_manifest": inputs,
    }
    return {**payload, "sha256": content_sha256(payload)}


def build_prediction_group_payload(
    *,
    run_id: uuid.UUID | str,
    metadata: Mapping[str, Any],
    predictions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate exact group completeness and return hash-covered stored fields."""
    normalized_run_id = _uuid(run_id)
    if not isinstance(metadata, Mapping):
        raise ValueError("prediction group metadata is required")
    required = ("match_id", "model_version_id", "play_type")
    if any(metadata.get(key) is None for key in required):
        raise ValueError("prediction group match, model version, and play type are required")
    expected = _expected_options(metadata)
    seen: set[str] = set()
    by_option: dict[str, Mapping[str, Any]] = {}
    prediction_times: set[str] = set()
    for prediction in predictions:
        if not isinstance(prediction, Mapping):
            raise ValueError("each prediction option must be a mapping")
        option = str(prediction.get("option_code", ""))
        if not option:
            raise ValueError("prediction option code is required")
        if option in seen:
            raise ValueError(f"duplicate option in prediction group: {option}")
        seen.add(option)
        for key in required:
            if key == "play_type":
                matches_group = str(prediction.get(key)) == str(metadata[key])
            else:
                try:
                    matches_group = int(prediction.get(key, -1)) == int(metadata[key])
                except TypeError, ValueError:
                    matches_group = False
            if not matches_group:
                raise ValueError(f"prediction {key} differs from group metadata")
        if str(prediction.get("play_type")) != str(metadata["play_type"]):
            raise ValueError("prediction play_type differs from group metadata")
        if "predict_time" in metadata and str(prediction.get("predict_time")) != str(
            metadata["predict_time"]
        ):
            raise ValueError("prediction time differs from group metadata")
        if prediction.get("predict_time") is None:
            raise ValueError("prediction time is required for each option")
        prediction_times.add(str(prediction["predict_time"]))
        by_option[option] = prediction
    if seen != set(expected):
        raise ValueError(
            f"prediction options do not match expected options: expected={expected}, actual={sorted(seen)}"
        )
    if len(prediction_times) != 1:
        raise ValueError("prediction options must share one prediction time")
    ordered_predictions = [by_option[option] for option in expected]
    vector = {option: float(by_option[option]["model_probability"]) for option in expected}
    market_variant = str(metadata.get("market_variant") or "")
    predict_time = metadata.get("predict_time") or ordered_predictions[0].get("predict_time")
    if str(predict_time) not in prediction_times:
        raise ValueError("group prediction time differs from its options")
    if predict_time is None:
        raise ValueError("prediction time is required")
    input_fence = metadata.get("input_fence")
    if input_fence is not None and not isinstance(input_fence, Mapping):
        raise ValueError("input fence must be a mapping")
    odds_snapshot_ids = metadata.get("odds_snapshot_ids") or {
        option: by_option[option].get("odds_snapshot_id") for option in expected
    }
    odds_snapshot_times = metadata.get("odds_snapshot_times") or {}
    artifact_identity = metadata.get("artifact_identity")
    provenance_status = str(metadata.get("provenance_status") or "incomplete")
    if provenance_status not in {"complete", "incomplete"}:
        raise ValueError("provenance_status must be complete or incomplete")
    prediction_outputs = [
        {key: value for key, value in dict(by_option[option]).items() if key not in {"input_fence"}}
        for option in expected
    ]
    output_payload = {
        "match_id": int(metadata["match_id"]),
        "model_version_id": int(metadata["model_version_id"]),
        "play_type": str(metadata["play_type"]),
        "market_variant": market_variant,
        "predict_time": str(predict_time),
        "expected_options": expected,
        "probability_vector": vector,
        "score_matrix": metadata.get("score_matrix"),
        "odds_snapshot_ids": odds_snapshot_ids,
        "odds_snapshot_times": odds_snapshot_times,
        "feature_snapshot_id": metadata.get("feature_snapshot_id"),
        "input_fence": input_fence,
        "artifact_identity": artifact_identity,
        "prediction_outputs": prediction_outputs,
    }
    return {
        **output_payload,
        "run_id": normalized_run_id,
        "output_sha256": content_sha256(output_payload),
        "predictions": ordered_predictions,
        "provenance_status": provenance_status,
    }


def create_prediction_run(
    conn: Any,
    *,
    run_id: uuid.UUID | str,
    ai_job_run_id: int | None,
    release_id: str,
    code_fingerprint: Mapping[str, Any],
    model_manifest: Sequence[Mapping[str, Any]],
    input_manifest: Mapping[str, Any],
    provenance_status: str,
) -> uuid.UUID:
    normalized_run_id = _uuid(run_id)
    if provenance_status not in {"complete", "incomplete"}:
        raise ValueError("provenance_status must be complete or incomplete")
    normalized_models = list(model_manifest)
    normalized_inputs = dict(input_manifest)
    codefp = dict(code_fingerprint)
    manifest = _run_manifest(release_id, codefp, normalized_models, normalized_inputs)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO model_prediction_runs (
                   id, ai_job_run_id, run_status, provenance_status, release_id,
                   code_fingerprint, model_manifest, input_manifest,
                   run_manifest, run_manifest_sha256,
                   model_manifest_sha256, input_manifest_sha256, started_at
               ) VALUES (%s, %s, 'running', %s, %s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp())""",
            (
                str(normalized_run_id),
                ai_job_run_id,
                provenance_status,
                release_id,
                Json(codefp),
                Json(normalized_models),
                Json(normalized_inputs),
                Json(manifest),
                manifest["sha256"],
                content_sha256(normalized_models),
                content_sha256(normalized_inputs),
            ),
        )
    conn.commit()
    return normalized_run_id


def update_prediction_run_manifest(
    conn: Any,
    *,
    run_id: uuid.UUID | str,
    model_manifest: Sequence[Mapping[str, Any]],
    input_manifest: Mapping[str, Any],
    provenance_status: str,
) -> None:
    normalized_run_id = _uuid(run_id)
    if provenance_status not in {"complete", "incomplete"}:
        raise ValueError("provenance_status must be complete or incomplete")
    models = list(model_manifest)
    inputs = dict(input_manifest)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT release_id, code_fingerprint FROM model_prediction_runs
               WHERE id=%s AND run_status='running'""",
            (str(normalized_run_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("running prediction run was not found")
        release_id, code_fingerprint = row
        manifest = _run_manifest(release_id, code_fingerprint, models, inputs)
        effective_provenance = (
            "complete"
            if provenance_status == "complete"
            and code_fingerprint.get("provenance_status", "complete") == "complete"
            else "incomplete"
        )
        cur.execute(
            """UPDATE model_prediction_runs
               SET model_manifest=%s, input_manifest=%s, run_manifest=%s,
                   run_manifest_sha256=%s, model_manifest_sha256=%s,
                   input_manifest_sha256=%s, provenance_status=%s
               WHERE id=%s AND run_status='running'""",
            (
                Json(models),
                Json(inputs),
                Json(manifest),
                manifest["sha256"],
                content_sha256(models),
                content_sha256(inputs),
                effective_provenance,
                str(normalized_run_id),
            ),
        )
        if cur.rowcount != 1:
            raise ValueError("running prediction run was not found")
    conn.commit()


def store_prediction_group(
    conn: Any,
    *,
    run_id: uuid.UUID | str,
    metadata: Mapping[str, Any],
    predictions: Sequence[Mapping[str, Any]],
) -> uuid.UUID:
    payload = build_prediction_group_payload(
        run_id=run_id, metadata=metadata, predictions=predictions
    )
    group_id = uuid.uuid4()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO model_prediction_groups (
                       id, run_id, match_id, model_version_id, play_type, market_variant,
                       predict_time, expected_options, probability_vector, score_matrix,
                       odds_snapshot_ids, odds_snapshot_times, feature_snapshot_id,
                       input_fence, artifact_identity, output_manifest,
                       provenance_status, output_sha256, group_status, created_at
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       'building', clock_timestamp()
                   )""",
                (
                    str(group_id),
                    str(payload["run_id"]),
                    payload["match_id"],
                    payload["model_version_id"],
                    payload["play_type"],
                    payload["market_variant"],
                    payload["predict_time"],
                    Json(payload["expected_options"]),
                    Json(payload["probability_vector"]),
                    Json(payload["score_matrix"]) if payload["score_matrix"] is not None else None,
                    Json(payload["odds_snapshot_ids"]),
                    Json(payload["odds_snapshot_times"]),
                    payload["feature_snapshot_id"],
                    Json(payload["input_fence"]) if payload["input_fence"] is not None else None,
                    Json(payload["artifact_identity"])
                    if payload["artifact_identity"] is not None
                    else None,
                    Json(
                        {
                            key: value
                            for key, value in payload.items()
                            if key
                            not in {"run_id", "output_sha256", "predictions", "provenance_status"}
                        }
                    ),
                    payload["provenance_status"],
                    payload["output_sha256"],
                ),
            )
        for ordinal, prediction in enumerate(payload["predictions"]):
            prediction_id = store_model_prediction(conn, dict(prediction), commit=False)
            if prediction_id is None:
                raise RuntimeError("prediction option insert returned no row id")
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO model_prediction_group_options
                           (group_id, option_code, prediction_id, ordinal)
                       VALUES (%s, %s, %s, %s)""",
                    (str(group_id), str(prediction["option_code"]), prediction_id, ordinal),
                )
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE model_prediction_groups
                   SET group_status = 'complete', completed_at = clock_timestamp()
                   WHERE id = %s AND group_status = 'building'""",
                (str(group_id),),
            )
            if cur.rowcount != 1:
                raise RuntimeError("prediction group could not be completed")
        conn.commit()
        return group_id
    except Exception:
        conn.rollback()
        raise


def finalize_prediction_run(
    conn: Any,
    *,
    run_id: uuid.UUID | str,
    run_status: str,
    error_message: str | None = None,
) -> None:
    normalized_run_id = _uuid(run_id)
    if run_status not in {"completed", "partial", "failed"}:
        raise ValueError("terminal run_status must be completed, partial, or failed")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT output_sha256 FROM model_prediction_groups
               WHERE run_id = %s AND group_status = 'complete'
               ORDER BY match_id, model_version_id, play_type, market_variant, id""",
            (str(normalized_run_id),),
        )
        outputs = [row[0] for row in cur.fetchall()]
        output_manifest_sha256 = content_sha256(outputs)
        cur.execute(
            """UPDATE model_prediction_runs
               SET run_status = %s, output_manifest_sha256 = %s,
                   error_message = %s, finished_at = clock_timestamp()
               WHERE id = %s AND run_status = 'running'""",
            (run_status, output_manifest_sha256, error_message, str(normalized_run_id)),
        )
        if cur.rowcount != 1:
            raise ValueError("running prediction run was not found")
    conn.commit()


def fail_prediction_run(conn: Any, run_id: uuid.UUID | str, error_message: str) -> None:
    normalized_run_id = _uuid(run_id)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM model_prediction_groups
               WHERE run_id = %s AND group_status = 'complete'""",
            (str(normalized_run_id),),
        )
        has_groups = int(cur.fetchone()[0]) > 0
    finalize_prediction_run(
        conn,
        run_id=normalized_run_id,
        run_status="partial" if has_groups else "failed",
        error_message=error_message,
    )
