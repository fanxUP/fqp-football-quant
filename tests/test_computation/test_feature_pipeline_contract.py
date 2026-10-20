"""Fixed responses for the existing feature write/read and model input boundary."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from scripts import feature_importance, feature_storage, prematch_feature_dataset
from scripts.jobs import run_feature_snapshot_build, run_model_prediction
from scripts.logistic_shadow_model import LogisticShadowProfile, probabilities_from_classifier

LEGACY_ORDER_SHA256 = "7fa4a2410defee9ff98349b361770b0c7eeaeeb5ea69d0b1395f332a9fa7e333"
AS_OF = "2026-10-16T18:00:00"


def _connection():
    conn = MagicMock()
    return conn, conn.cursor.return_value.__enter__.return_value


def _snapshot():
    values = {column: float(i + 1) for i, column in enumerate(feature_importance.FEATURE_COLUMNS)}
    values.update(
        match_id=101,
        snapshot_time="2026-10-16T17:00:00",
        feature_version="v3_upset_risk",
        home_team_id=7,
        away_team_id=8,
        competition_season_id=9,
        stadium_id=10,
        team_market_value_diff=0,
        raw_feature_refs={"dimension_coverage": {"lineup": 0.5}, "synthetic": True},
        home_lineup_confirmed=False,
        away_lineup_confirmed=True,
        home_must_win=False,
        away_must_win=True,
        home_draw_enough=None,
        away_draw_enough=False,
        home_key_absence_count=0,
        precipitation=0,
        wind_speed_10m=None,
        unregistered_input="must never become a SQL identifier",
    )
    return values


def _read_fixture(snapshot):
    from scripts.feature_schema import SNAPSHOT_READ_COLUMNS

    conn, cursor = _connection()
    record = {**snapshot, "id": 88}
    cursor.fetchone.return_value = tuple(record.get(column) for column in SNAPSHOT_READ_COLUMNS)
    result = feature_storage.load_latest_match_feature_snapshot(conn, 101, as_of=AS_OF)
    return result, conn, cursor


def test_write_includes_every_declared_feature_and_existing_metadata():
    conn, cursor = _connection()
    cursor.fetchone.return_value = (88,)
    snapshot = _snapshot()

    assert feature_storage.store_match_feature_snapshot(conn, snapshot) == 88
    sql, parameters = cursor.execute.call_args.args
    columns = re.search(r"INSERT INTO match_feature_snapshots\s*\((.*?)\)\s*VALUES", sql, re.S)[1]
    # Strip SQL comments so a comment mentioning a field cannot satisfy this assertion.
    columns = re.sub(r"--[^\n]*", "", columns)
    identifiers = {column.strip() for column in columns.split(",")}
    for column in (*feature_importance.FEATURE_COLUMNS, "stadium_id", "team_market_value_diff"):
        assert column in identifiers, column
        assert parameters[column] == snapshot[column], column
    assert "unregistered_input" not in identifiers
    assert "unregistered_input" not in parameters
    assert json.loads(parameters["raw_feature_refs"]) == snapshot["raw_feature_refs"]
    assert "ON CONFLICT" not in sql
    conn.commit.assert_called_once()


@pytest.mark.parametrize("value", [None, 0, False])
def test_write_does_not_replace_missing_zero_or_false(value):
    conn, cursor = _connection()
    snapshot = _snapshot()
    snapshot.update(home_lineup_confirmed=value, precipitation=value, lineup_strength_diff=value)
    feature_storage.store_match_feature_snapshot(conn, snapshot)
    parameters = cursor.execute.call_args.args[1]
    for column in ("home_lineup_confirmed", "precipitation", "lineup_strength_diff"):
        assert parameters[column] is value


def test_legacy_order_is_frozen_and_common_to_training_consumers():
    from scripts.feature_schema import FEATURE_COLUMNS

    assert isinstance(FEATURE_COLUMNS, tuple)
    assert len(FEATURE_COLUMNS) == len(set(FEATURE_COLUMNS)) == 55
    assert hashlib.sha256("\n".join(FEATURE_COLUMNS).encode()).hexdigest() == LEGACY_ORDER_SHA256
    assert feature_importance.FEATURE_COLUMNS is FEATURE_COLUMNS
    assert prematch_feature_dataset.FEATURE_COLUMNS is FEATURE_COLUMNS


def test_write_and_read_keep_all_declared_values_and_metadata():
    snapshot = _snapshot()
    write_conn, write_cursor = _connection()
    feature_storage.store_match_feature_snapshot(write_conn, snapshot)
    persisted = dict(write_cursor.execute.call_args.args[1])
    persisted["raw_feature_refs"] = json.loads(persisted["raw_feature_refs"])

    loaded, conn, _ = _read_fixture(persisted)
    for column in (*feature_importance.FEATURE_COLUMNS, "stadium_id", "team_market_value_diff"):
        assert loaded[column] == snapshot[column], column
    for column in ("match_id", "snapshot_time", "feature_version", "raw_feature_refs"):
        assert loaded[column] == snapshot[column]
    assert loaded["home_lineup_confirmed"] is False
    assert loaded["wind_speed_10m"] is None
    conn.commit.assert_not_called()


def test_reader_uses_prediction_and_kickoff_boundaries_and_deterministic_tie_break():
    _, _, cursor = _read_fixture(_snapshot())
    sql, parameters = cursor.execute.call_args.args
    assert "fs.snapshot_time < m.kickoff_time" in sql
    assert "fs.snapshot_time <= %(as_of)s" in sql
    assert "ORDER BY fs.snapshot_time DESC, fs.id DESC" in sql
    assert "LIMIT 1" in sql
    assert parameters == {"match_id": 101, "as_of": datetime.fromisoformat(AS_OF)}
    assert "SELECT *" not in sql


def test_reader_returns_none_for_no_eligible_snapshot():
    conn, cursor = _connection()
    cursor.fetchone.return_value = None
    assert feature_storage.load_latest_match_feature_snapshot(conn, 101, as_of=AS_OF) is None
    conn.commit.assert_not_called()


@pytest.mark.parametrize("as_of", ["2026-10-16T18:00:00+08:00", "2026-10-16T10:00:00Z"])
def test_reader_does_not_silently_reinterpret_aware_cutoff_as_legacy_naive_time(as_of):
    conn, _ = _connection()
    with pytest.raises(ValueError, match="business-local naive"):
        feature_storage.load_latest_match_feature_snapshot(conn, 101, as_of=as_of)
    conn.cursor.assert_not_called()


def test_reader_accepts_explicit_legacy_business_datetime():
    conn, cursor = _connection()
    cursor.fetchone.return_value = None
    cutoff = datetime.fromisoformat(AS_OF)
    feature_storage.load_latest_match_feature_snapshot(conn, 101, as_of=cutoff)
    assert cursor.execute.call_args.args[1]["as_of"] == cutoff


def test_reader_fails_on_incomplete_database_row_instead_of_silently_truncating():
    conn, cursor = _connection()
    cursor.fetchone.return_value = (88,)
    with pytest.raises(ValueError):
        feature_storage.load_latest_match_feature_snapshot(conn, 101, as_of=AS_OF)


def test_prediction_wrapper_reuses_the_common_snapshot_reader():
    with patch.object(run_model_prediction, "load_latest_match_feature_snapshot") as reader:
        conn = MagicMock()
        reader.return_value = {"id": 88}
        assert run_model_prediction._latest_feature_snapshot(conn, 101, as_of=AS_OF) == {"id": 88}
        reader.assert_called_once_with(conn, 101, as_of=AS_OF)


def test_prediction_job_passes_its_prediction_time_to_snapshot_reader():
    conn, cursor = _connection()
    cursor.fetchall.return_value = []
    with (
        patch.object(run_model_prediction, "capture_prediction_input_fence"),
        patch.object(run_model_prediction, "_latest_feature_snapshot", return_value=None) as reader,
    ):
        assert run_model_prediction._predict_match_play_type(
            conn, 101, "主队", "客队", "spf", {}, -0.08, None, AS_OF
        ) == (0, 0)
    reader.assert_called_once_with(conn, 101, as_of=AS_OF)


def test_dataset_preserves_frozen_column_order_zero_false_and_missing():
    conn, cursor = _connection()
    snapshot = _snapshot()
    columns = feature_importance.FEATURE_COLUMNS
    cursor.fetchall.return_value = [(AS_OF, *(snapshot[column] for column in columns), 2)]
    rows, labels, dates = prematch_feature_dataset.load_settled_pre_kickoff_dataset(conn)
    assert rows.shape == (1, 55)
    assert rows[0, columns.index("home_lineup_confirmed")] == 0
    assert rows[0, columns.index("away_lineup_confirmed")] == 1
    assert rows[0, columns.index("precipitation")] == 0
    assert np.isnan(rows[0, columns.index("wind_speed_10m")])
    assert labels.tolist() == [2]
    assert dates == [AS_OF]


def test_model_uses_only_its_declared_subset_in_saved_order_after_full_read():
    snapshot, _, _ = _read_fixture(_snapshot())
    subset = ("away_lineup_confirmed", "precipitation", "home_lineup_confirmed", "wind_speed_10m")
    profile = LogisticShadowProfile("unused.joblib", subset, 100, 25, 1.0)
    classifier = MagicMock()
    classifier.classes_ = [0, 1, 2]
    classifier.predict_proba.return_value = [[0.2, 0.3, 0.5]]
    assert probabilities_from_classifier(classifier, profile, snapshot) == {
        "0": 0.2,
        "1": 0.3,
        "3": 0.5,
    }
    values = classifier.predict_proba.call_args.args[0][0]
    assert len(values) == len(subset)
    assert values[:3] == [1.0, 0.0, 0.0]
    assert np.isnan(values[3])


def test_actual_build_task_passes_enrichment_fields_through_storage_and_reader():
    """Mock source builders, then run real assembly, INSERT and common readback."""
    conn, cursor = _connection()
    cursor.fetchall.return_value = [(101,)]
    cursor.fetchone.side_effect = [
        (101, "主队", "客队", "瑞典超级联赛", datetime(2026, 10, 16, 20), {}),
        (88,),
    ]
    snapshot = _snapshot()
    columns = feature_importance.FEATURE_COLUMNS

    def subset(*names):
        return {name: snapshot[name] for name in names}

    lineup = {
        **subset(*columns[7:15], *columns[20:23]),
        "has_lineup_data": True,
        "covered_team_count": 2,
    }
    injury = {**subset(*columns[15:20]), "has_injury_data": True, "covered_team_count": 2}
    travel = {**subset(*columns[26:30], "stadium_id"), "has_travel_data": True}
    weather = subset(*columns[30:35])
    motivation = {
        **subset(*columns[35:42]),
        "has_motivation_data": True,
        "covered_team_count": 2,
    }
    tournament = {**subset(*columns[42:47]), "has_tournament_incentive_data": True}
    dependencies = {
        "scripts.features.build_lineup_strength.build_lineup_features": lineup,
        "scripts.features.build_injury_impact.build_injury_features": injury,
        "scripts.features.build_travel_features.build_travel_features": travel,
        "scripts.features.build_motivation_score.build_motivation_features": motivation,
        "scripts.features.build_tournament_incentive.build_tournament_incentive_features": tournament,
    }
    with ExitStack() as stack:
        for target, value in dependencies.items():
            stack.enter_context(patch(target, return_value=value))
        stack.enter_context(
            patch.object(run_feature_snapshot_build, "get_db")
        ).return_value.__enter__.return_value = conn
        stack.enter_context(
            patch.object(
                run_feature_snapshot_build,
                "_business_now_naive",
                return_value=datetime(2026, 10, 16, 17),
            )
        )
        stack.enter_context(
            patch.object(run_feature_snapshot_build, "_resolve_team_id", side_effect=[7, 8])
        )
        stack.enter_context(
            patch.object(
                run_feature_snapshot_build, "_resolve_competition_season_id", return_value=9
            )
        )
        stack.enter_context(
            patch.object(run_feature_snapshot_build, "_resolve_match_stadium_id", return_value=10)
        )
        stack.enter_context(
            patch.object(
                run_feature_snapshot_build, "compute_team_form", return_value={"matches_played": 0}
            )
        )
        stack.enter_context(
            patch.object(run_feature_snapshot_build, "compute_rest_days", return_value=3)
        )
        stack.enter_context(
            patch.object(
                run_feature_snapshot_build, "_load_collected_weather", return_value=(weather, True)
            )
        )
        stack.enter_context(
            patch.object(
                run_feature_snapshot_build,
                "load_pre_kickoff_upset_risk",
                return_value=subset(*columns[47:52]),
            )
        )
        stack.enter_context(
            patch.object(
                run_feature_snapshot_build,
                "_load_latest_open_odds",
                return_value=[
                    {"play_type": "spf", "option_code": code, "sp_value": value}
                    for code, value in [("h", 2.0), ("d", 3.0), ("a", 4.0)]
                ],
            )
        )
        result = run_feature_snapshot_build._run_impl(match_id=101)

    assert result["snapshots_built"] == 1
    assert result["failed_count"] == 0
    assert len(result["dimension_rates"]) == 10
    sql, parameters = cursor.execute.call_args.args
    assert "INSERT INTO match_feature_snapshots" in sql
    for column in columns[7:23] + columns[26:52]:
        assert parameters[column] == snapshot[column], column
    assert parameters["home_key_absence_count"] == 0
    assert parameters["home_lineup_confirmed"] is False
    assert parameters["wind_speed_10m"] is None
    parameters = {**parameters, "raw_feature_refs": json.loads(parameters["raw_feature_refs"])}
    loaded, _, _ = _read_fixture(parameters)
    assert loaded["data_completeness_score"] == 80
    assert loaded["raw_feature_refs"]["dimension_coverage"]["lineup"] == 1
    assert loaded["home_lineup_confirmed"] is False
    assert loaded["precipitation"] == 0


@pytest.mark.parametrize(
    "hour, expected_id", [(16, None), (17, 5), (18, 5), (19, 2), (20, 2), (21, 2)]
)
def test_reader_selection_on_fixed_in_memory_sql_rows(hour, expected_id):
    """Exercise SQL filtering/order; SQLite is not PostgreSQL persistence evidence."""
    from scripts.feature_schema import SNAPSHOT_READ_COLUMNS

    with closing(sqlite3.connect(":memory:")) as database:
        database.execute("CREATE TABLE official_matches (id INTEGER, kickoff_time TEXT)")
        database.execute("INSERT INTO official_matches VALUES (101, '2026-10-16T20:00:00')")
        # Only SELECT semantics are exercised. No PostgreSQL type/precision claim.
        fields = ", ".join(f"{column} TEXT" for column in SNAPSHOT_READ_COLUMNS)
        database.execute(f"CREATE TABLE match_feature_snapshots ({fields})")
        for identifier, match, stamp in [
            (1, 101, "17:00:00"),
            (2, 101, "19:00:00"),
            (3, 101, "20:00:00"),
            (4, 101, "21:00:00"),
            (5, 101, "17:00:00"),
            (6, 102, "17:00:00"),
        ]:
            database.execute(
                "INSERT INTO match_feature_snapshots (id, match_id, snapshot_time) VALUES (?, ?, ?)",
                (identifier, match, f"2026-10-16T{stamp}"),
            )

        class ReaderCursor:
            def execute(self, sql, parameters):
                statement = re.sub(r"%\((\w+)\)s", r":\1", sql)
                parameters = {**parameters, "as_of": parameters["as_of"].isoformat()}
                self.result = database.execute(statement, parameters)

            def fetchone(self):
                return self.result.fetchone()

        @contextmanager
        def cursor():
            yield ReaderCursor()

        conn = MagicMock()
        conn.cursor.side_effect = cursor
        result = feature_storage.load_latest_match_feature_snapshot(
            conn, 101, as_of=f"2026-10-16T{hour:02d}:00:00"
        )
        assert (int(result["id"]) if result else None) == expected_id
