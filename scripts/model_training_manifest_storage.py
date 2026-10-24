"""Persist and validate immutable Maher training manifests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from psycopg2.extras import Json

from scripts.model_artifact_identity import canonical_json_bytes, training_manifest_sha256


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("training manifest canonical bytes contain duplicate keys")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _validated_manifest(
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], bytes, str, int, int]:
    if not isinstance(manifest, Mapping):
        raise ValueError("training manifest is missing or invalid")
    value = dict(manifest)
    training_manifest_sha256(value)
    included = value.get("included")
    excluded = value.get("excluded")
    if not isinstance(included, list) or not isinstance(excluded, list):
        raise ValueError("training manifest included/excluded rows must be arrays")
    canonical = canonical_json_bytes(value)
    return (
        value,
        canonical,
        hashlib.sha256(canonical).hexdigest(),
        len(included),
        len(excluded),
    )


def persist_training_manifest(
    conn: Any,
    model_version_id: int,
    manifest: Mapping[str, Any],
) -> None:
    """Insert one manifest for a newly created model version; never update it."""
    value, canonical, content_digest, included_count, excluded_count = _validated_manifest(manifest)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO model_training_manifests (
                   model_version_id, manifest_json, manifest_canonical,
                   training_manifest_sha256, content_sha256,
                   included_count, excluded_count
               ) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                int(model_version_id),
                Json(value, dumps=lambda item: canonical_json_bytes(item).decode("utf-8")),
                canonical,
                value["sha256"],
                content_digest,
                included_count,
                excluded_count,
            ),
        )


def load_training_manifest(conn: Any, model_version_id: int) -> dict[str, Any] | None:
    """Return the stored manifest only when all persisted identity fields agree."""
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT p106_training_manifest_read")
        try:
            cur.execute(
                """SELECT manifest_json, manifest_canonical, training_manifest_sha256,
                          content_sha256, included_count, excluded_count
                   FROM model_training_manifests
                   WHERE model_version_id=%s""",
                (int(model_version_id),),
            )
            row = cur.fetchone()
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT p106_training_manifest_read")
            cur.execute("RELEASE SAVEPOINT p106_training_manifest_read")
            return None
        else:
            cur.execute("RELEASE SAVEPOINT p106_training_manifest_read")
    if row is None:
        return None

    (
        manifest_json,
        canonical_value,
        stored_training_digest,
        stored_content_digest,
        included_count,
        excluded_count,
    ) = row
    if not isinstance(manifest_json, Mapping):
        raise ValueError("stored training manifest JSON is invalid")
    if not isinstance(canonical_value, (bytes, bytearray, memoryview)):
        raise ValueError("stored training manifest canonical bytes are invalid")
    canonical = bytes(canonical_value)
    if hashlib.sha256(canonical).hexdigest() != stored_content_digest:
        raise ValueError("stored training manifest content SHA-256 does not match")
    try:
        parsed = json.loads(
            canonical.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("stored training manifest canonical bytes are invalid JSON") from exc
    if not isinstance(parsed, dict) or parsed != dict(manifest_json):
        raise ValueError("stored training manifest bytes do not match JSONB")
    _, expected_canonical, expected_content_digest, expected_included, expected_excluded = (
        _validated_manifest(parsed)
    )
    if (
        expected_canonical != canonical
        or expected_content_digest != stored_content_digest
        or parsed.get("sha256") != stored_training_digest
        or expected_included != included_count
        or expected_excluded != excluded_count
    ):
        raise ValueError("stored training manifest identity fields do not match content")
    return parsed
