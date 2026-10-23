from __future__ import annotations

import hashlib
import uuid

import pytest

from scripts.model_prediction_run_identity import canonical_json_bytes
from scripts.model_prediction_run_storage import (
    _normalized_output_summary,
    build_prediction_group_payload,
    store_prediction_group,
)


def _predictions(options: tuple[str, ...] = ("3", "1", "0")) -> list[dict]:
    return [
        {
            "match_id": 901,
            "model_version_id": 22,
            "odds_snapshot_id": 600 + index,
            "feature_snapshot_id": 77,
            "predict_time": "2026-10-23T10:00:00",
            "play_type": "spf",
            "option_code": option,
            "raw_model_probability": probability,
            "model_probability": probability,
            "market_probability": probability,
            "break_even_probability": probability,
            "market_edge": 0.0,
            "breakeven_edge": 0.0,
            "ev": 0.0,
            "validation_status": "valid",
            "validation_errors": [],
            "calculation_version": "test-v1",
        }
        for index, (option, probability) in enumerate(zip(options, (0.5, 0.25, 0.25), strict=False))
    ]


def test_prediction_group_requires_exact_unique_option_set() -> None:
    with pytest.raises(ValueError, match="expected options"):
        build_prediction_group_payload(
            run_id=uuid.uuid4(),
            metadata={
                "match_id": 901,
                "model_version_id": 22,
                "play_type": "spf",
                "expected_options": ["3", "1", "0"],
            },
            predictions=_predictions(("3", "1")),
        )

    duplicate = _predictions()
    duplicate[-1]["option_code"] = "1"
    with pytest.raises(ValueError, match="duplicate option"):
        build_prediction_group_payload(
            run_id=uuid.uuid4(),
            metadata={
                "match_id": 901,
                "model_version_id": 22,
                "play_type": "spf",
                "expected_options": ["3", "1", "0"],
            },
            predictions=duplicate,
        )


@pytest.mark.parametrize("invalid_match_id", ["not-an-integer", None])
def test_prediction_group_rejects_non_integer_match_identity(invalid_match_id) -> None:
    predictions = _predictions()
    predictions[0]["match_id"] = invalid_match_id

    with pytest.raises(ValueError, match="prediction match_id differs from group metadata"):
        build_prediction_group_payload(
            run_id=uuid.uuid4(),
            metadata={
                "match_id": 901,
                "model_version_id": 22,
                "play_type": "spf",
                "expected_options": ["3", "1", "0"],
            },
            predictions=predictions,
        )


def test_prediction_group_payload_hash_covers_vector_and_input_references() -> None:
    metadata = {
        "match_id": 901,
        "model_version_id": 22,
        "play_type": "spf",
        "market_variant": "",
        "predict_time": "2026-10-23T10:00:00",
        "expected_options": ["3", "1", "0"],
        "odds_snapshot_ids": {"3": 600, "1": 601, "0": 602},
        "feature_snapshot_id": 77,
        "input_fence": {"match_id": 901, "input_version": 4},
        "score_matrix": {"0:0": 0.1, "1:0": 0.2},
    }

    first = build_prediction_group_payload(
        run_id=uuid.uuid4(), metadata=metadata, predictions=_predictions()
    )
    altered = build_prediction_group_payload(
        run_id=uuid.uuid4(),
        metadata={**metadata, "odds_snapshot_ids": {"3": 700, "1": 701, "0": 702}},
        predictions=_predictions(),
    )

    assert first["probability_vector"] == {"0": 0.25, "1": 0.25, "3": 0.5}
    assert first["output_sha256"] != altered["output_sha256"]
    assert first["output_manifest_canonical"] == canonical_json_bytes(first["output_manifest"])
    assert hashlib.sha256(first["output_manifest_canonical"]).hexdigest() == first["output_sha256"]


def test_storage_rolls_back_when_an_option_insert_fails() -> None:
    class BrokenConnection:
        def __init__(self):
            self.rolled_back = False
            self.committed = False

        def cursor(self):
            raise RuntimeError("database unavailable")

        def rollback(self):
            self.rolled_back = True

        def commit(self):
            self.committed = True

    conn = BrokenConnection()
    with pytest.raises(RuntimeError, match="database unavailable"):
        store_prediction_group(
            conn,
            run_id=uuid.uuid4(),
            metadata={
                "match_id": 901,
                "model_version_id": 22,
                "play_type": "spf",
                "expected_options": ["3", "1", "0"],
            },
            predictions=_predictions(),
        )
    assert conn.rolled_back is True
    assert conn.committed is False


def test_partial_run_requires_an_explicit_output_summary() -> None:
    with pytest.raises(ValueError, match="output summary is required"):
        _normalized_output_summary(
            None,
            completed_groups=1,
            run_status="partial",
            error_message="failed after writing one group",
        )


def test_failed_run_without_summary_marks_output_counts_unknown() -> None:
    summary = _normalized_output_summary(
        None,
        completed_groups=1,
        run_status="failed",
        error_message="failed before completion summary was produced",
    )

    assert summary == {
        "expected_groups": None,
        "completed_groups": 1,
        "skipped_groups": None,
        "missing_groups": [],
        "input_updates_skipped": None,
        "counts_complete": False,
        "completion_reason": "run_failed_before_output_summary",
    }
