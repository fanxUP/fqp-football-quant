"""Pure contract guards for the explicit observation batch pilot."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from scripts import observed_feature_pipeline as pipeline
from scripts.feature_schema import FEATURE_COLUMNS
from scripts.observation_storage import ObservationCutoff


def context(**changes):
    return dict(home_team_id=7, away_team_id=8, kickoff_at="2026-11-01T12:00:00+00:00", **changes)


@pytest.mark.parametrize("bad", [None, {}, {"home_team_id": 7}, {"extra": 1}])
def test_context_requires_exact_explicit_declaration(bad):
    with pytest.raises(ValueError, match="context"):
        pipeline.validate_context(bad)


@pytest.mark.parametrize(
    "key,value",
    [
        ("home_team_id", True),
        ("away_team_id", 0),
        ("home_team_id", "7"),
        ("away_team_id", 7),
        ("kickoff_at", "2026-11-01T12:00:00"),
        ("kickoff_at", "not-a-date"),
    ],
)
def test_invalid_context_is_not_coerced(key, value):
    data = context()
    data[key] = value
    with pytest.raises(ValueError, match="context"):
        pipeline.validate_context(data)


def test_context_normalizes_only_explicit_timezone():
    data = context()
    data["kickoff_at"] = "2026-11-01T20:00:00+08:00"
    assert pipeline.validate_context(data) == context()


@pytest.mark.parametrize(
    "columns,required",
    [
        ((), ()),
        (("invented",), ()),
        (("temperature_2m", "temperature_2m"), ()),
        (("temperature_2m",), ("home_lineup_confirmed",)),
        (("temperature_2m",), ("temperature_2m", "temperature_2m")),
    ],
)
def test_model_column_guards_run_before_database(columns, required):
    conn = MagicMock()
    with pytest.raises(ValueError, match="columns"):
        pipeline.load_observed_feature_input(
            conn,
            batch_id=1,
            match_id=1,
            as_of=datetime.now(UTC),
            feature_columns=columns,
            required_fields=required,
        )
    conn.cursor.assert_not_called()


def test_shared_dataset_entry_delegates_exact_batch_and_order():
    from scripts.prematch_feature_dataset import load_observed_feature_input

    args = dict(
        batch_id=3,
        match_id=4,
        as_of=datetime.now(UTC),
        feature_columns=("away_lineup_confirmed", "temperature_2m"),
        required_fields=(),
    )
    conn = MagicMock()
    with patch.object(
        pipeline, "load_observed_feature_input", return_value={"status": "ready"}
    ) as read:
        assert load_observed_feature_input(conn, **args) == {"status": "ready"}
        read.assert_called_once_with(conn, **args)


def test_existing_builder_entry_uses_explicit_cutoff_and_caller_transaction():
    from scripts.jobs.run_feature_snapshot_build import build_observed_feature_batch

    conn = MagicMock()
    cutoff = ObservationCutoff("00000000-0000-0000-0000-000000000001", datetime.now(UTC))
    args = dict(match_id=1, cutoff=cutoff, context=context())
    with patch.object(pipeline, "build_observed_feature_batch", return_value=77) as build:
        assert build_observed_feature_batch(conn, **args) == 77
        build.assert_called_once_with(conn, **args)
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()


def test_default_full_schema_is_unchanged():
    assert len(FEATURE_COLUMNS) == 55
    assert pipeline.BUILDER_VERSION != "v4_observed_form"
