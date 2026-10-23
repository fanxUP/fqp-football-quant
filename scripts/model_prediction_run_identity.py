"""Stable content identities for prediction runs and the models they execute."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _normalize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, bool):
                raise TypeError("boolean JSON object keys are not supported")
            if isinstance(key, str):
                normalized_key = key
            elif isinstance(key, int):
                normalized_key = str(key)
            else:
                raise TypeError("JSON object keys must be strings or integers")
            if normalized_key in normalized:
                raise ValueError(f"duplicate canonical JSON key: {normalized_key}")
            normalized[normalized_key] = _normalize_json(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON number must be finite")
        return 0.0 if value == 0.0 else value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON with stable key order and strict numeric/UTF-8 handling."""
    return json.dumps(
        _normalize_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def verify_prediction_run_manifest(
    *,
    run_manifest: Mapping[str, Any],
    run_manifest_sha256: str,
    model_manifest: Sequence[Mapping[str, Any]],
    model_manifest_sha256: str,
    input_manifest: Mapping[str, Any],
    input_manifest_sha256: str,
) -> None:
    """Reject a run whose persisted manifest or component hashes disagree."""
    if not isinstance(run_manifest, Mapping):
        raise ValueError("run manifest is missing or invalid")
    if not isinstance(model_manifest, Sequence) or isinstance(model_manifest, (str, bytes)):
        raise ValueError("model manifest is missing or invalid")
    if not isinstance(input_manifest, Mapping):
        raise ValueError("input manifest is missing or invalid")
    if not _is_sha256(run_manifest_sha256):
        raise ValueError("run manifest SHA-256 is invalid")
    if not _is_sha256(model_manifest_sha256) or content_sha256(list(model_manifest)) != (
        model_manifest_sha256
    ):
        raise ValueError("model manifest SHA-256 does not match content")
    if not _is_sha256(input_manifest_sha256) or content_sha256(dict(input_manifest)) != (
        input_manifest_sha256
    ):
        raise ValueError("input manifest SHA-256 does not match content")

    manifest_payload = {key: value for key, value in run_manifest.items() if key != "sha256"}
    recorded_digest = run_manifest.get("sha256")
    if (
        not _is_sha256(recorded_digest)
        or recorded_digest != run_manifest_sha256
        or content_sha256(manifest_payload) != run_manifest_sha256
    ):
        raise ValueError("run manifest SHA-256 does not match content")
    if run_manifest.get("model_manifest") != _stable_model_manifest(model_manifest):
        raise ValueError("run manifest model manifest does not match stored model manifest")
    if run_manifest.get("input_manifest") != _stable_input_manifest(input_manifest):
        raise ValueError("run manifest input manifest does not match stored input manifest")
    source_files = run_manifest.get("source_files")
    if not isinstance(source_files, Mapping) or any(
        not _is_sha256(digest) for digest in source_files.values()
    ):
        raise ValueError("run manifest source fingerprint is invalid")
    if content_sha256(dict(source_files)) != run_manifest.get("source_fingerprint"):
        raise ValueError("run manifest source fingerprint does not match its files")


def verify_prediction_artifact_binding(
    model_manifest: Sequence[Mapping[str, Any]],
    artifact_identity: Mapping[str, Any],
    *,
    model_version_id: int,
) -> None:
    """Require a complete group identity to equal its hashed run manifest entry."""
    if not isinstance(model_manifest, Sequence) or isinstance(model_manifest, (str, bytes)):
        raise ValueError("model manifest is missing or invalid")
    if not isinstance(artifact_identity, Mapping):
        raise ValueError("prediction artifact identity is missing or invalid")
    entries = [
        item
        for item in model_manifest
        if isinstance(item, Mapping) and item.get("model_version_id") == model_version_id
    ]
    if len(entries) != 1 or dict(entries[0]) != dict(artifact_identity):
        raise ValueError("prediction artifact identity does not match the run model manifest")
    if artifact_identity.get("provenance_status") != "complete":
        raise ValueError("prediction artifact provenance is incomplete")
    if not _is_sha256(artifact_identity.get("parameters_sha256")):
        raise ValueError("prediction artifact parameter SHA-256 is invalid")
    artifact = artifact_identity.get("artifact")
    if not isinstance(artifact, Mapping) or not _is_sha256(artifact.get("sha256")):
        raise ValueError("prediction artifact content identity is invalid")
    size_bytes = artifact.get("size_bytes")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise ValueError("prediction artifact size is invalid")
    if artifact.get("kind") == "inline_parameters":
        if artifact.get("sha256") != artifact_identity["parameters_sha256"]:
            raise ValueError("inline prediction artifact digest does not match parameters")
    elif artifact.get("kind") == "external_file":
        relative_path = artifact.get("relative_path")
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or Path(relative_path).is_absolute()
            or ".." in Path(relative_path).parts
        ):
            raise ValueError("external prediction artifact path is invalid")
    else:
        raise ValueError("prediction artifact kind is unsupported")
    if artifact_identity.get("model_name") == "maher_poisson":
        if not _is_sha256(artifact_identity.get("training_manifest_sha256")) or not _is_sha256(
            artifact_identity.get("training_identity_sha256")
        ):
            raise ValueError("Maher training artifact identity is incomplete")


def verify_prediction_group_output_manifest(
    *,
    output_manifest: Mapping[str, Any],
    output_sha256: str,
    output_manifest_canonical: bytes | bytearray | memoryview | None = None,
    match_id: int,
    model_version_id: int,
    play_type: str,
    market_variant: str,
    predict_time: Any | None = None,
    expected_options: Sequence[str],
    probability_vector: Mapping[str, Any],
) -> None:
    """Verify the hash and group-facing fields of a persisted output manifest."""
    if not isinstance(output_manifest, Mapping):
        raise ValueError("prediction output manifest is missing or invalid")
    _verify_persisted_json_hash(
        value=dict(output_manifest),
        digest=output_sha256,
        serialized=output_manifest_canonical,
        label="prediction output manifest",
    )
    expected = sorted(str(option) for option in expected_options)
    expected_predict_time = (
        (predict_time.isoformat() if hasattr(predict_time, "isoformat") else str(predict_time))
        if predict_time is not None
        else None
    )
    if (
        output_manifest.get("match_id") != match_id
        or output_manifest.get("model_version_id") != model_version_id
        or output_manifest.get("play_type") != play_type
        or output_manifest.get("market_variant") != market_variant
        or (
            expected_predict_time is not None
            and output_manifest.get("predict_time") != expected_predict_time
        )
        or sorted(str(option) for option in output_manifest.get("expected_options", [])) != expected
        or output_manifest.get("probability_vector") != dict(probability_vector)
    ):
        raise ValueError("prediction output manifest does not match its group")
    prediction_outputs = output_manifest.get("prediction_outputs")
    if not isinstance(prediction_outputs, list):
        raise ValueError("prediction output manifest options are missing")
    if [
        str(item.get("option_code")) for item in prediction_outputs if isinstance(item, Mapping)
    ] != (expected):
        raise ValueError("prediction output manifest options do not match the group")
    if any(not isinstance(item, Mapping) for item in prediction_outputs):
        raise ValueError("prediction output manifest contains an invalid option")


def verify_prediction_run_output_manifest(
    *,
    output_manifest: Mapping[str, Any],
    output_manifest_sha256: str,
    output_manifest_canonical: bytes | bytearray | memoryview | None,
    output_summary: Mapping[str, Any],
    expected_group_hashes: Sequence[str],
    required_group_sha256: str | None = None,
) -> None:
    """Verify the run digest and its persisted group/summary bindings."""
    if not isinstance(output_manifest, Mapping):
        raise ValueError("prediction run output manifest is missing or invalid")
    _verify_persisted_json_hash(
        value=dict(output_manifest),
        digest=output_manifest_sha256,
        serialized=output_manifest_canonical,
        label="prediction run output manifest",
    )
    groups = output_manifest.get("groups")
    if not isinstance(groups, list) or groups != list(expected_group_hashes):
        raise ValueError("prediction run output groups do not match stored groups")
    if output_manifest.get("summary") != dict(output_summary):
        raise ValueError("prediction run output summary does not match stored summary")
    if required_group_sha256 is not None and required_group_sha256 not in groups:
        raise ValueError("prediction group is not included in the parent run output manifest")
    if any(not _is_sha256(group_digest) for group_digest in groups):
        raise ValueError("prediction run output manifest contains an invalid group digest")
    if int(output_summary.get("completed_groups", -1)) != len(groups):
        raise ValueError("prediction run output summary does not match its groups")


def _verify_persisted_json_hash(
    *,
    value: Mapping[str, Any],
    digest: str,
    serialized: bytes | bytearray | memoryview | None,
    label: str,
) -> None:
    if not _is_sha256(digest):
        raise ValueError(f"{label} SHA-256 is invalid")
    if serialized is None:
        if content_sha256(dict(value)) != digest:
            raise ValueError(f"{label} SHA-256 does not match content")
        return
    if not isinstance(serialized, (bytes, bytearray, memoryview)):
        raise ValueError(f"{label} serialized content is invalid")
    raw = bytes(serialized)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"{label} SHA-256 does not match persisted bytes")
    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise ValueError(f"{label} serialized content is invalid JSON") from exc
    if parsed != dict(value):
        raise ValueError(f"{label} serialized bytes do not match stored content")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def fingerprint_runtime_sources(
    source_root: Path,
    source_paths: Sequence[str],
) -> dict[str, Any]:
    """Hash the exact relative source files loaded by the prediction process."""
    root = source_root.resolve()
    files: dict[str, str] = {}
    for relative_path in sorted(set(source_paths)):
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"runtime source path escapes root: {relative_path}")
        if not path.is_file():
            raise ValueError(f"runtime source is unavailable: {relative_path}")
        files[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"files": files, "sha256": content_sha256(files)}


def _stable_model_manifest(models: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_json(model) for model in models]
    return sorted(
        normalized,
        key=lambda model: (
            str(model.get("model_name", "")),
            int(model.get("model_version_id", 0)),
        ),
    )


def _stable_input_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_json(value)
    if "match_ids" in normalized:
        normalized["match_ids"] = sorted(set(normalized["match_ids"]))
    if "markets" in normalized:
        normalized["markets"] = sorted(normalized["markets"], key=lambda item: (item[0], item[1]))
    return normalized


def build_run_manifest(
    *,
    release_id: str,
    source_root: Path,
    source_paths: Sequence[str],
    model_manifest: Sequence[Mapping[str, Any]],
    input_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic run manifest; wall-clock time is intentionally absent."""
    if not isinstance(release_id, str) or not release_id.strip():
        raise ValueError("release_id is required")
    source_fingerprint = fingerprint_runtime_sources(source_root, source_paths)
    payload = {
        "schema_version": "fqp.model-prediction-run/v1",
        "release_id": release_id.strip(),
        "source_fingerprint": source_fingerprint["sha256"],
        "source_files": source_fingerprint["files"],
        "model_manifest": _stable_model_manifest(model_manifest),
        "input_manifest": _stable_input_manifest(input_manifest),
    }
    return {**payload, "sha256": content_sha256(payload)}


def _incomplete_identity(
    model_version_id: int,
    model_name: str,
    parameters: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "model_version_id": int(model_version_id),
        "model_name": model_name,
        "provenance_status": "incomplete",
        "parameters_sha256": content_sha256(parameters),
        "artifact": None,
        "reason": reason,
    }


def build_model_artifact_identity(
    model_version_id: int,
    model_name: str,
    parameters: Mapping[str, Any] | None,
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Hash inline parameters or a confined external file without loading it."""
    if not isinstance(parameters, Mapping):
        return _incomplete_identity(model_version_id, model_name, {}, "parameters_unavailable")
    params_sha256 = content_sha256(parameters)
    artifact_path = parameters.get("artifact_path")
    if artifact_path is not None:
        if not isinstance(artifact_path, str) or not artifact_path.strip():
            return _incomplete_identity(
                model_version_id, model_name, parameters, "artifact_path_invalid"
            )
        if artifact_root is None:
            return _incomplete_identity(
                model_version_id, model_name, parameters, "artifact_root_unconfigured"
            )
        root = artifact_root.resolve()
        candidate = Path(artifact_path)
        candidate = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if not candidate.is_relative_to(root):
            return _incomplete_identity(
                model_version_id, model_name, parameters, "artifact_path_outside_root"
            )
        if not candidate.is_file():
            return _incomplete_identity(
                model_version_id, model_name, parameters, "artifact_file_unavailable"
            )
        artifact_bytes = candidate.read_bytes()
        relative_path = candidate.relative_to(root).as_posix()
        artifact = {
            "kind": "external_file",
            "relative_path": relative_path,
            "format": candidate.suffix.lower().lstrip(".") or "unknown",
            "size_bytes": len(artifact_bytes),
            "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        }
        status = "complete"
        reason = None
    else:
        artifact = {
            "kind": "inline_parameters",
            "format": "application/json",
            "size_bytes": len(canonical_json_bytes(parameters)),
            "sha256": params_sha256,
        }
        status = "complete"
        reason = None
    training_manifest_sha256 = None
    training_identity_sha256 = None
    if model_name == "maher_poisson":
        maher_identity = parameters.get("_artifact_identity")
        if not isinstance(maher_identity, Mapping):
            status = "incomplete"
            reason = "training_manifest_identity_missing"
        else:
            from scripts.model_artifact_identity import verify_artifact_identity

            try:
                verify_artifact_identity(parameters)
                training_manifest_sha256 = maher_identity["training_manifest_sha256"]
                training_identity_sha256 = maher_identity["identity_sha256"]
            except TypeError, ValueError:
                status = "incomplete"
                reason = "training_manifest_identity_invalid"
                training_manifest_sha256 = None
                training_identity_sha256 = None
    identity = {
        "model_version_id": int(model_version_id),
        "model_name": model_name,
        "provenance_status": status,
        "parameters_sha256": params_sha256,
        "artifact": artifact,
        "reason": reason,
    }
    if model_name == "maher_poisson":
        identity["training_manifest_sha256"] = training_manifest_sha256
        identity["training_identity_sha256"] = training_identity_sha256
    return identity
