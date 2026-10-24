from __future__ import annotations

from scripts.model_prediction_run_identity import canonical_json_bytes, content_sha256
from scripts.model_prediction_run_loader import load_latest_prediction_group


def _artifact_identity(model_version_id=22):
    return {
        "model_version_id": model_version_id,
        "model_name": "market_baseline",
        "provenance_status": "complete",
        "parameters_sha256": "a" * 64,
        "artifact": {
            "kind": "inline_parameters",
            "format": "application/json",
            "size_bytes": 1,
            "sha256": "a" * 64,
        },
    }


def _output_manifest(artifact_identity=None):
    return {
        "match_id": 901,
        "model_version_id": 22,
        "play_type": "spf",
        "market_variant": "",
        "predict_time": "2026-10-23T10:00:00",
        "expected_options": ["0", "1", "3"],
        "probability_vector": {"0": 0.25, "1": 0.25, "3": 0.5},
        "artifact_identity": artifact_identity or _artifact_identity(),
        "prediction_outputs": [
            {"option_code": "0", "model_probability": 0.25},
            {"option_code": "1", "model_probability": 0.25},
            {"option_code": "3", "model_probability": 0.5},
        ],
    }


def _complete_group_row(*, output_manifest=None, digest=None, parent_identity=None):
    output_manifest = output_manifest or _output_manifest()
    digest = digest or content_sha256(output_manifest)
    parent_identity = parent_identity or _artifact_identity()
    model_manifest = [parent_identity]
    input_manifest = {"match_ids": [901]}
    run_payload = {
        "schema_version": "fqp.model-prediction-run/v1",
        "release_id": "test-release",
        "source_fingerprint": content_sha256({}),
        "source_files": {},
        "model_manifest": model_manifest,
        "input_manifest": input_manifest,
    }
    run_manifest = {**run_payload, "sha256": content_sha256(run_payload)}
    summary = {
        "expected_groups": 1,
        "completed_groups": 1,
        "skipped_groups": 0,
        "missing_groups": [],
        "input_updates_skipped": 0,
        "completion_reason": "predictions_completed",
    }
    run_output_manifest = {"groups": [digest], "summary": summary}
    return (
        "group-2",
        "run-2",
        901,
        22,
        "spf",
        "",
        "2026-10-23T10:00:00",
        ["3", "1", "0"],
        {"3": 0.5, "1": 0.25, "0": 0.25},
        digest,
        "complete",
        output_manifest,
        canonical_json_bytes(output_manifest),
        "completed",
        "complete",
        run_manifest,
        run_manifest["sha256"],
        model_manifest,
        content_sha256(model_manifest),
        input_manifest,
        content_sha256(input_manifest),
        summary,
        run_output_manifest,
        content_sha256(run_output_manifest),
        canonical_json_bytes(run_output_manifest),
        [digest],
    )


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, results):
        self.results = iter(results)
        self.cursors = []

    def cursor(self):
        cursor = _Cursor(next(self.results))
        self.cursors.append(cursor)
        return cursor


def test_loader_chooses_complete_group_before_loading_its_rows():
    conn = _Connection(
        [
            [_complete_group_row()],
            [
                (100, "3", 0.5, 0.4, 600, 77, "2026-10-23T10:00:00", "spf"),
                (101, "1", 0.25, 0.3, 601, 77, "2026-10-23T10:00:00", "spf"),
                (102, "0", 0.25, 0.3, 602, 77, "2026-10-23T10:00:00", "spf"),
            ],
        ]
    )

    loaded = load_latest_prediction_group(conn, match_id=901, model_version_id=22, play_type="spf")

    assert loaded["group_id"] == "group-2"
    assert [row["option_code"] for row in loaded["options"]] == ["3", "1", "0"]
    assert "group_status = 'complete'" in conn.cursors[0].query
    assert "run_status IN" in conn.cursors[0].query
    assert "'completed','partial'" in conn.cursors[0].query.replace(" ", "").replace("\n", "")
    assert "model_prediction_group_options" in conn.cursors[1].query


def test_loader_does_not_fall_back_to_legacy_after_a_complete_group_exists():
    conn = _Connection(
        [
            [_complete_group_row()],
            [],
        ]
    )

    loaded = load_latest_prediction_group(conn, match_id=901, model_version_id=22, play_type="spf")

    assert loaded["options"] == []
    assert loaded["status"] == "incomplete_group"
    assert len(conn.cursors) == 2
    assert "FROM model_predictions" not in conn.cursors[1].query


def test_loader_rejects_a_completed_group_with_a_forged_output_digest():
    manifest = _output_manifest()
    digest = "f" * 64
    conn = _Connection([[_complete_group_row(output_manifest=manifest, digest=digest)]])

    loaded = load_latest_prediction_group(conn, match_id=901, model_version_id=22, play_type="spf")

    assert loaded["status"] == "invalid_integrity"
    assert loaded["options"] == []
    assert len(conn.cursors) == 1


def test_loader_rejects_artifact_identity_not_bound_to_parent_run():
    parent_identity = _artifact_identity()
    forged_identity = {**parent_identity, "parameters_sha256": "b" * 64}
    manifest = _output_manifest(artifact_identity=forged_identity)
    conn = _Connection(
        [[_complete_group_row(output_manifest=manifest, parent_identity=parent_identity)]]
    )

    loaded = load_latest_prediction_group(conn, match_id=901, model_version_id=22, play_type="spf")

    assert loaded["status"] == "invalid_integrity"
    assert loaded["options"] == []
    assert "does not match" in loaded["integrity_error"]
