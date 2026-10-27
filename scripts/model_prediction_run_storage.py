"""Transactional persistence for complete prediction runs and output groups."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from psycopg2 import Binary
from psycopg2.extras import Json

from scripts.model_prediction_run_identity import canonical_json_bytes, content_sha256
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


_PREDICTION_OUTPUT_FIELDS = (
    "match_id",
    "model_version_id",
    "odds_snapshot_id",
    "feature_snapshot_id",
    "predict_time",
    "play_type",
    "option_code",
    "raw_model_probability",
    "model_probability",
    "market_probability",
    "probability_lower_bound",
    "probability_upper_bound",
    "uncertainty_score",
    "adjusted_probability",
    "fair_odds",
    "ev",
    "confidence_score",
    "risk_score",
    "break_even_probability",
    "market_edge",
    "breakeven_edge",
    "validation_status",
    "validation_errors",
    "calculation_version",
    "uncertainty_reason",
)
_PREDICTION_NUMERIC_SCALES = {
    "raw_model_probability": 6,
    "model_probability": 6,
    "market_probability": 6,
    "probability_lower_bound": 6,
    "probability_upper_bound": 6,
    "uncertainty_score": 6,
    "adjusted_probability": 6,
    "fair_odds": 4,
    "ev": 6,
    "confidence_score": 4,
    "risk_score": 4,
    "break_even_probability": 6,
    "market_edge": 6,
    "breakeven_edge": 6,
}


def _stored_prediction_fields(prediction: Mapping[str, Any]) -> dict[str, Any]:
    fields = {name: prediction.get(name) for name in _PREDICTION_OUTPUT_FIELDS}
    fields["raw_model_probability"] = prediction.get(
        "raw_model_probability", prediction.get("model_probability")
    )
    fields["validation_errors"] = prediction.get("validation_errors", [])
    fields["uncertainty_reason"] = dict(prediction.get("uncertainty_reason") or {})
    for name, scale in _PREDICTION_NUMERIC_SCALES.items():
        value = fields[name]
        if value is None:
            continue
        if isinstance(value, bool):
            raise ValueError(f"prediction output {name} must be numeric")
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"prediction output {name} must be numeric") from exc
        if not number.is_finite():
            raise ValueError(f"prediction output {name} must be finite")
        fields[name] = float(number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP))
    return fields


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
    source_predictions = [by_option[option] for option in expected]
    stored_fields = [_stored_prediction_fields(item) for item in source_predictions]
    ordered_predictions = [
        {**dict(source), **fields}
        for source, fields in zip(source_predictions, stored_fields, strict=True)
    ]
    vector = {
        option: float(fields["model_probability"])
        for option, fields in zip(expected, stored_fields, strict=True)
    }
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
    prediction_outputs = stored_fields
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
    output_manifest_canonical = canonical_json_bytes(output_payload)
    return {
        **output_payload,
        "run_id": normalized_run_id,
        "output_manifest": output_payload,
        "output_manifest_canonical": output_manifest_canonical,
        "output_sha256": hashlib.sha256(output_manifest_canonical).hexdigest(),
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
               WHERE id=%s AND run_status='running' FOR UPDATE""",
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


def _normalized_output_summary(
    summary: Mapping[str, Any] | None,
    *,
    completed_groups: int,
    run_status: str,
    error_message: str | None,
) -> dict[str, Any]:
    if summary is None:
        if run_status != "failed":
            raise ValueError("prediction output summary is required for completed or partial runs")
        summary = {
            "expected_groups": None,
            "completed_groups": completed_groups,
            "skipped_groups": None,
            "missing_groups": [],
            "input_updates_skipped": None,
            "counts_complete": False,
            "completion_reason": "run_failed_before_output_summary",
        }
    if not isinstance(summary, Mapping):
        raise ValueError("prediction output summary must be a mapping")
    normalized = dict(summary)
    counts_complete = normalized.setdefault("counts_complete", True)
    if not isinstance(counts_complete, bool):
        raise ValueError("prediction output summary counts_complete must be a boolean")
    integer_fields = ["completed_groups"]
    if counts_complete:
        integer_fields.extend(("expected_groups", "skipped_groups", "input_updates_skipped"))
    elif run_status != "failed":
        raise ValueError("unknown prediction output counts are allowed only for failed runs")
    for field in integer_fields:
        value = normalized.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"prediction output summary {field} must be a non-negative integer")
    missing_groups = normalized.get("missing_groups")
    if not isinstance(missing_groups, list) or any(
        not isinstance(item, Mapping) or not isinstance(item.get("reason"), str)
        for item in missing_groups
    ):
        raise ValueError("prediction output summary missing_groups must contain reasoned records")
    if normalized["completed_groups"] != completed_groups:
        raise ValueError("prediction output summary count does not match completed groups")
    if counts_complete:
        if normalized["expected_groups"] != (
            normalized["completed_groups"] + normalized["skipped_groups"]
        ):
            raise ValueError("prediction output summary expected count is inconsistent")
        if len(missing_groups) != normalized["skipped_groups"]:
            raise ValueError("prediction output summary requires one reason per skipped group")
    elif (
        any(
            normalized.get(field) is not None
            for field in ("expected_groups", "skipped_groups", "input_updates_skipped")
        )
        or missing_groups
    ):
        raise ValueError("unknown prediction output counts must be represented without estimates")
    completion_reason = normalized.get("completion_reason")
    if not isinstance(completion_reason, str) or not completion_reason.strip():
        raise ValueError("prediction output summary completion_reason is required")
    if run_status == "completed" and (
        not counts_complete or normalized["skipped_groups"] or normalized["input_updates_skipped"]
    ):
        raise ValueError("completed prediction run cannot have skipped output groups")
    if run_status == "partial" and not (
        counts_complete
        and (normalized["skipped_groups"] or normalized["input_updates_skipped"] or error_message)
    ):
        raise ValueError("partial prediction run requires a recorded omission or failure")
    return normalized


def store_prediction_group(
    conn: Any,
    *,
    run_id: uuid.UUID | str,
    metadata: Mapping[str, Any],
    predictions: Sequence[Mapping[str, Any]],
) -> uuid.UUID:
    group_id = uuid.uuid4()
    try:
        normalized_metadata = dict(metadata)
        if normalized_metadata.get("provenance_status") == "complete":
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT provenance_status FROM model_prediction_runs WHERE id=%s",
                    (str(_uuid(run_id)),),
                )
                parent = cur.fetchone()
            if parent is not None and parent[0] != "complete":
                # A group cannot claim complete lineage when the parent run
                # manifest records any missing source or artifact identity.
                normalized_metadata["provenance_status"] = "incomplete"
        normalized_predictions: list[dict[str, Any]] = []
        bound_input_fences: dict[str, dict[str, Any]] = {}
        for prediction in predictions:
            normalized = dict(prediction)
            token = normalized.get("input_fence")
            if token is not None:
                from scripts.prediction_input_fence import bind_prediction_input_fence

                bound = bind_prediction_input_fence(
                    conn,
                    int(normalized["match_id"]),
                    token,
                    odds_snapshot_id=normalized.get("odds_snapshot_id"),
                )
                reason = dict(normalized.get("uncertainty_reason") or {})
                if "input_fence" in reason:
                    raise ValueError(
                        "input_fence is reserved for the internal pre-computation token"
                    )
                reason["input_fence"] = bound
                normalized["uncertainty_reason"] = reason
                bound_input_fences[str(normalized.get("option_code", ""))] = bound
            normalized_predictions.append(normalized)
        payload = build_prediction_group_payload(
            run_id=run_id, metadata=normalized_metadata, predictions=normalized_predictions
        )
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO model_prediction_groups (
                       id, run_id, match_id, model_version_id, play_type, market_variant,
                       predict_time, expected_options, probability_vector, score_matrix,
                       odds_snapshot_ids, odds_snapshot_times, feature_snapshot_id,
                       input_fence, artifact_identity, output_manifest,
                       output_manifest_canonical, provenance_status, output_sha256,
                       group_status, created_at
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
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
                    Json(payload["output_manifest"]),
                    Binary(payload["output_manifest_canonical"]),
                    payload["provenance_status"],
                    payload["output_sha256"],
                ),
            )
        for ordinal, prediction in enumerate(payload["predictions"]):
            prediction_id = store_model_prediction(
                conn,
                dict(prediction),
                commit=False,
                bound_input_fence=bound_input_fences.get(str(prediction["option_code"])),
            )
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
    output_summary: Mapping[str, Any] | None = None,
    commit: bool = True,
) -> None:
    normalized_run_id = _uuid(run_id)
    if run_status not in {"completed", "partial", "failed"}:
        raise ValueError("terminal run_status must be completed, partial, or failed")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id FROM model_prediction_runs
               WHERE id=%s AND run_status='running' FOR UPDATE""",
            (str(normalized_run_id),),
        )
        if cur.fetchone() is None:
            raise ValueError("running prediction run was not found")
        cur.execute(
            """SELECT output_sha256 FROM model_prediction_groups
               WHERE run_id = %s AND group_status = 'complete'
               ORDER BY match_id, model_version_id, play_type, market_variant, id""",
            (str(normalized_run_id),),
        )
        outputs = [row[0] for row in cur.fetchall()]
        summary = _normalized_output_summary(
            output_summary,
            completed_groups=len(outputs),
            run_status=run_status,
            error_message=error_message,
        )
        output_manifest = {"groups": outputs, "summary": summary}
        output_manifest_canonical = canonical_json_bytes(output_manifest)
        output_manifest_sha256 = hashlib.sha256(output_manifest_canonical).hexdigest()
        cur.execute(
            """UPDATE model_prediction_runs
               SET run_status = %s, output_manifest_sha256 = %s, output_summary = %s,
                   output_manifest = %s, output_manifest_canonical = %s,
                   error_message = %s, finished_at = clock_timestamp()
               WHERE id = %s AND run_status = 'running'""",
            (
                run_status,
                output_manifest_sha256,
                Json(summary),
                Json(output_manifest),
                Binary(output_manifest_canonical),
                error_message,
                str(normalized_run_id),
            ),
        )
        if cur.rowcount != 1:
            raise ValueError("running prediction run was not found")
    if commit:
        conn.commit()


def fail_prediction_run(
    conn: Any, run_id: uuid.UUID | str, error_message: str, *, commit: bool = True
) -> None:
    normalized_run_id = _uuid(run_id)
    finalize_prediction_run(
        conn,
        run_id=normalized_run_id,
        run_status="failed",
        error_message=error_message,
        commit=commit,
    )
