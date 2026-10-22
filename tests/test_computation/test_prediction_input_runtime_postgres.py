"""Existing-task consumer, real isolated PG and synthetic evidence only."""

from unittest.mock import patch

import psycopg2
import pytest

from scripts import prediction_input_revisions as revisions
from scripts import prediction_input_runtime as runtime
from scripts.feature_batch_storage import load_feature_batch
from scripts.features.build_weather_features import (
    compute_temperature_goal_expectation_adjustment,
    compute_weather_impact,
)
from scripts.observed_feature_pipeline import BUILDER_VERSION
from scripts.observed_maher_shadow import _AUDIT_FIELDS, build_observed_maher_shadow
from scripts.prediction_input_updates import InputUpdateSuperseded
from tests.test_computation import test_prediction_input_revisions_postgres as prior

connect = prior.connect
pg = prior.pg
match_id = prior.match_id
match = prior.match
consumer_factory = prior.consumer_factory
consumer = prior.consumer
ready = prior.ready
query = prior.query


def drain(pg, match, **args):
    pg.commit()
    return runtime.drain_prediction_input_updates(pg, match_id=match["id"], **args)


def receipts(pg, match):
    return query(
        pg,
        "SELECT consumer_key,result_refs FROM prediction_input_consumptions "
        "WHERE match_id=%s AND consumer_key LIKE %s ORDER BY completed_at,consumer_key",
        (match["id"], "observed-readiness/%"),
    )


def shadow_receipt(pg, match):
    rows = query(
        pg,
        "SELECT result_refs FROM prediction_input_consumptions "
        "WHERE match_id=%s AND consumer_key=%s",
        (match["id"], runtime.MAHER_SHADOW_CONSUMER),
    )
    return rows[0][0] if rows else None


def _trained_maher_parameters(home_team_id=11, away_team_id=22):
    return {
        "converged": True,
        "attack": {str(home_team_id): 0.12, str(away_team_id): -0.04},
        "defense": {str(home_team_id): -0.03, str(away_team_id): 0.02},
        "team_match_counts": {str(home_team_id): 40, str(away_team_id): 36},
        "home_advantage": 0.16,
        "league_intercept": 0.0,
        "n_matches": 120,
    }


def _shadow_fixture(temperature=18.0):
    match_id, batch_id, cutoff_id = 77, 902, "12f470e2-2d7f-44ac-9075-f28323d8469d"
    home_team_id, away_team_id = 11, 22
    context = {
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "kickoff_at": "2026-10-23T12:00:00+00:00",
    }
    features = {}
    source_indexes = {}
    for offset, name in enumerate(_AUDIT_FIELDS, start=1):
        features[name] = {
            "observation_indexes": [offset],
            "derivation": {
                "context": context,
                "resolution": {"candidates": [{"index": offset, "revision_id": 500 + offset}]},
            },
        }
        source_indexes[name] = 500 + offset
    batch = {
        "id": batch_id,
        "match_id": match_id,
        "cutoff_id": cutoff_id,
        "builder_version": BUILDER_VERSION,
        "features": features,
    }
    snapshot = {
        "feature_version": BUILDER_VERSION,
        "feature_batch_id": batch_id,
        "observation_cutoff_id": cutoff_id,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "temperature_2m": temperature,
        "home_lineup_confirmed": None,
        "away_lineup_confirmed": None,
        "home_key_absence_count": None,
        "away_key_absence_count": None,
    }
    feature_input = {
        "status": "ready",
        "match_id": match_id,
        "batch_id": batch_id,
        "cutoff_id": cutoff_id,
        "feature_columns": list(_AUDIT_FIELDS),
        "field_statuses": {name: "unknown" for name in _AUDIT_FIELDS},
        "snapshot": snapshot,
    }
    feature_input["field_statuses"]["temperature_2m"] = "value"
    return batch, feature_input, source_indexes


def test_temperature_only_adjustment_matches_existing_heat_component():
    weather = {
        "temperature_2m": 36.0,
        "precipitation": 0.0,
        "wind_speed_10m": 0.0,
        "wind_gusts_10m": 0.0,
        "relative_humidity_2m": 60.0,
    }
    assert (
        compute_temperature_goal_expectation_adjustment(36.0)
        == compute_weather_impact(weather)["goal_expectation_adjustment"]
    )
    assert compute_temperature_goal_expectation_adjustment(18.0) == 0.0
    with pytest.raises(ValueError):
        compute_temperature_goal_expectation_adjustment(float("nan"))


def test_maher_shadow_uses_exact_temperature_and_keeps_player_inputs_audit_only():
    batch, feature_input, source_indexes = _shadow_fixture(temperature=40.0)
    result = build_observed_maher_shadow(
        model_version_id=91,
        model_parameters=_trained_maher_parameters(),
        feature_input=feature_input,
        batch=batch,
        input_version=3,
        as_of="2026-10-22T12:00:00+00:00",
    )
    cool_batch, cool_input, _ = _shadow_fixture(temperature=18.0)
    cool = build_observed_maher_shadow(
        model_version_id=91,
        model_parameters=_trained_maher_parameters(),
        feature_input=cool_input,
        batch=cool_batch,
        input_version=3,
        as_of="2026-10-22T12:00:00+00:00",
    )
    assert result["status"] == "computed_shadow"
    assert result["applied_features"] == ["temperature_2m"]
    assert result["source_revision_ids"]["temperature_2m"] == [source_indexes["temperature_2m"]]
    assert result["not_applied_features"]
    assert result["probabilities"] != cool["probabilities"]
    assert abs(sum(result["probabilities"].values()) - 1.0) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in result["probabilities"].values())

    odds_batch, odds_input, _ = _shadow_fixture(temperature=40.0)
    odds_input["snapshot"]["market_odds"] = {"home": 1.01, "draw": 100.0, "away": 100.0}
    odds_input["snapshot"]["market_probabilities"] = {
        "3": 0.99,
        "1": 0.005,
        "0": 0.005,
    }
    odds_result = build_observed_maher_shadow(
        model_version_id=91,
        model_parameters=_trained_maher_parameters(),
        feature_input=odds_input,
        batch=odds_batch,
        input_version=3,
        as_of="2026-10-22T12:00:00+00:00",
    )
    assert odds_result["probabilities"] == result["probabilities"]

    lineup_batch, lineup_input, _ = _shadow_fixture(temperature=40.0)
    for name, value in (
        ("home_lineup_confirmed", True),
        ("away_lineup_confirmed", True),
        ("home_key_absence_count", 0),
        ("away_key_absence_count", 2),
    ):
        lineup_input["field_statuses"][name] = "value"
        lineup_input["snapshot"][name] = value
    lineup_result = build_observed_maher_shadow(
        model_version_id=91,
        model_parameters=_trained_maher_parameters(),
        feature_input=lineup_input,
        batch=lineup_batch,
        input_version=3,
        as_of="2026-10-22T12:00:00+00:00",
    )
    assert lineup_result["probabilities"] == result["probabilities"]
    assert lineup_result["feature_values"]["home_lineup_confirmed"] is True


def test_maher_shadow_fails_closed_without_temperature_model_or_exact_batch():
    batch, feature_input, _ = _shadow_fixture(temperature=18.0)
    feature_input["field_statuses"]["temperature_2m"] = "unknown"
    feature_input["snapshot"]["market_probabilities"] = {
        "3": 0.99,
        "1": 0.005,
        "0": 0.005,
    }
    missing_temperature = build_observed_maher_shadow(
        model_version_id=91,
        model_parameters=_trained_maher_parameters(),
        feature_input=feature_input,
        batch=batch,
        input_version=3,
        as_of="2026-10-22T12:00:00+00:00",
    )
    assert missing_temperature["status"] == "observation_unavailable"
    assert missing_temperature["probabilities"] is None

    invalid_temperature_batch, invalid_temperature_input, _ = _shadow_fixture(temperature=18.0)
    invalid_temperature_input["snapshot"]["temperature_2m"] = None
    invalid_temperature = build_observed_maher_shadow(
        model_version_id=91,
        model_parameters=_trained_maher_parameters(),
        feature_input=invalid_temperature_input,
        batch=invalid_temperature_batch,
        input_version=3,
        as_of="2026-10-22T12:00:00+00:00",
    )
    assert invalid_temperature["status"] == "observation_unavailable"
    assert invalid_temperature["reason"] == "temperature_invalid"
    assert invalid_temperature["probabilities"] is None

    _, usable_input, _ = _shadow_fixture(temperature=18.0)
    unavailable_model = build_observed_maher_shadow(
        model_version_id=None,
        model_parameters=None,
        feature_input=usable_input,
        batch=batch,
        input_version=3,
        as_of="2026-10-22T12:00:00+00:00",
    )
    assert unavailable_model["status"] == "model_unavailable"
    assert unavailable_model["probabilities"] is None

    mismatched_batch, mismatched_input, _ = _shadow_fixture(temperature=18.0)
    mismatched_input["snapshot"]["home_team_id"] = 999
    mismatch = build_observed_maher_shadow(
        model_version_id=91,
        model_parameters=_trained_maher_parameters(),
        feature_input=mismatched_input,
        batch=mismatched_batch,
        input_version=3,
        as_of="2026-10-22T12:00:00+00:00",
    )
    assert mismatch["status"] == "observed_input_unavailable"
    assert mismatch["probabilities"] is None


def test_runtime_builds_exact_batches_for_both_plays_without_artifact_claim(pg, match, ready):
    result = drain(pg, match)
    assert result["status"] == "ok" and result["completed"] == 2
    assert result["claimed"] == 2 and result["failed"] == result["deferred"] == 0
    rows = receipts(pg, match)
    assert {r[0] for r in rows} == set(runtime.CONSUMERS.values())
    for _, refs in rows:
        revision = revisions.load_prediction_input_revision(pg, refs["input_revision_id"])
        assert not revision["recommendation_eligible"]
        assert not revision["decision"]["model_independent"]
        batch = load_feature_batch(pg, revision["feature_batch_id"])
        assert batch["cutoff_id"] == revision["observation_cutoff_id"]
        assert len(batch["features"]) == 55
    assert drain(pg, match)["claimed"] == 0


def test_runtime_retains_maher_shadow_from_exact_batch_without_official_prediction_write(
    pg, match, ready
):
    prior.pipeline.weather(pg, match, 40.0, effective_at=ready["kickoff"])
    before_predictions = query(
        pg, "SELECT count(*) FROM model_predictions WHERE match_id=%s", (match["id"],)
    )[0][0]
    model_parameters = _trained_maher_parameters(match["home_team_id"], match["away_team_id"])
    with patch.object(
        runtime,
        "_active_maher_model",
        return_value=(901, model_parameters, None),
    ):
        result = drain(pg, match)

    assert result["status"] == "ok"
    assert result["completed"] == 2 and result["shadow_completed"] == 1
    refs = shadow_receipt(pg, match)
    assert refs is not None
    shadow = refs["maher_shadow"]
    assert shadow["status"] == "computed_shadow", shadow
    assert shadow["model_version_id"] == 901
    assert type(shadow["feature_batch_id"]) is int and shadow["feature_batch_id"] > 0
    assert shadow["applied_features"] == ["temperature_2m"]
    assert shadow["adjustment"]["observed_celsius"] == 40.0
    assert abs(sum(shadow["probabilities"].values()) - 1.0) < 1e-9
    revision = revisions.load_prediction_input_revision(pg, refs["input_revision_id"])
    assert revision["feature_batch_id"] == shadow["feature_batch_id"]
    assert revision["observation_cutoff_id"] == shadow["observation_cutoff_id"]
    assert not revision["recommendation_eligible"]
    assert (
        query(pg, "SELECT count(*) FROM model_predictions WHERE match_id=%s", (match["id"],))[0][0]
        == before_predictions
    )


@pytest.mark.parametrize(
    "change",
    [
        "sale_status='closed'",
        "match_status='cancelled'",
        "kickoff_time=timezone('Asia/Shanghai',clock_timestamp())-interval '1 second'",
        "sale_stop_time=NULL",
        "sale_stop_time=timezone('Asia/Shanghai',clock_timestamp())",
    ],
)
def test_non_actionable_records_terminal_receipt_without_fake_batch(pg, match, ready, change):
    query(pg, "UPDATE official_matches SET " + change + " WHERE id=%s", (match["id"],))
    before = query(pg, "SELECT count(*) FROM feature_batches WHERE match_id=%s", (match["id"],))
    result = drain(pg, match)
    assert result["blocked"] == 2 and result["completed"] == 0 and result["failed"] == 0
    for _, refs in receipts(pg, match):
        assert refs["outcome"] == "not_actionable" and refs["research_only"]
        assert refs["recommendation_eligible"] is False
        assert "input_revision_id" not in refs and "feature_batch_id" not in refs
    assert (
        query(pg, "SELECT count(*) FROM feature_batches WHERE match_id=%s", (match["id"],))
        == before
    )
    assert drain(pg, match)["claimed"] == 0


def test_missing_identity_is_acknowledged_then_bounded_refresh_rechecks(pg, match, ready):
    query(pg, "DELETE FROM team_aliases WHERE team_id=%s", (match["home_team_id"],))
    result = drain(pg, match)
    assert result["blocked"] == 2
    assert all(refs["outcome"] == "awaiting_verification" for _, refs in receipts(pg, match))
    assert drain(pg, match)["claimed"] == 0
    name = query(pg, "SELECT home_team_name FROM official_matches WHERE id=%s", (match["id"],))[0][
        0
    ]
    query(
        pg,
        "INSERT INTO team_aliases(team_id,source_name,alias_name) VALUES (%s,'sporttery',%s)",
        (match["home_team_id"], name),
    )
    pg.commit()
    # Inject only the private refresh interval, no source timestamps or history edits.
    with patch.object(revisions, "_IDENTITY_RECHECK_SECONDS", 0):
        assert drain(pg, match)["completed"] == 2
    assert len(receipts(pg, match)) == 4


def test_reopened_official_sale_creates_new_version_without_reviving_terminal(pg, match, ready):
    query(pg, "UPDATE official_matches SET sale_status='closed' WHERE id=%s", (match["id"],))
    assert drain(pg, match)["blocked"] == 2
    old = receipts(pg, match)
    query(pg, "UPDATE official_matches SET sale_status='selling' WHERE id=%s", (match["id"],))
    assert drain(pg, match)["completed"] == 2
    assert receipts(pg, match)[:2] == old


def test_superseded_computation_rolls_back_batch_and_releases_own_claim(pg, match, ready):
    before = query(pg, "SELECT count(*) FROM feature_batches WHERE match_id=%s", (match["id"],))
    with patch.object(
        runtime, "complete_prediction_input_revision", side_effect=InputUpdateSuperseded("new")
    ):
        result = drain(pg, match)
    assert result["deferred"] == 2 and result["failed"] == 0
    assert receipts(pg, match) == []
    assert (
        query(pg, "SELECT count(*) FROM feature_batches WHERE match_id=%s", (match["id"],))
        == before
    )
    assert drain(pg, match)["completed"] == 2


def test_unexpected_error_is_visible_and_retry_does_not_duplicate_receipts(pg, match, ready):
    with patch.object(runtime, "build_observed_feature_batch", side_effect=RuntimeError("fixture")):
        result = drain(pg, match)
    assert result["status"] == "failed" and result["failed"] == 2
    assert all(e["error_type"] == "RuntimeError" for e in result["errors"])
    assert receipts(pg, match) == []
    assert drain(pg, match)["completed"] == 2


def test_consumer_least_privilege_can_build_and_complete(pg, match, ready):
    query(pg, "SET ROLE fqp_input_consumer")
    assert drain(pg, match)["completed"] == 2
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        query(pg, "UPDATE official_matches SET sale_status='closed' WHERE id=%s", (match["id"],))
    pg.rollback()


@pytest.mark.parametrize(
    "args", [{"limit": 0}, {"limit": 33}, {"limit": True}, {"match_id": False}, {"match_id": 0}]
)
def test_runtime_rejects_unbounded_or_invalid_call(pg, args):
    with pytest.raises(ValueError):
        runtime.drain_prediction_input_updates(pg, **args)


def test_runtime_refuses_callers_open_transaction(pg):
    query(pg, "SELECT 1")
    with pytest.raises(ValueError, match="idle"):
        runtime.drain_prediction_input_updates(pg)


def test_timeouts_are_local_and_preserve_stricter_settings(pg, match, ready):
    query(pg, "SET statement_timeout='2s'")
    query(pg, "SET lock_timeout='100ms'")
    pg.commit()
    seen = []
    original = runtime.build_observed_feature_batch

    def build(*args, **kwargs):
        seen.append(
            (query(pg, "SHOW statement_timeout")[0][0], query(pg, "SHOW lock_timeout")[0][0])
        )
        return original(*args, **kwargs)

    with patch.object(runtime, "build_observed_feature_batch", side_effect=build):
        assert drain(pg, match)["completed"] == 2
    assert seen == [("2s", "100ms")] * 3
    assert query(pg, "SHOW lock_timeout") == [("100ms",)]


def test_existing_feature_job_runs_real_consumer_with_no_legacy_matches(
    pg, match, ready, monkeypatch
):
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    from scripts.jobs import run_feature_snapshot_build as job

    pg.commit()

    @contextmanager
    def database():
        yield pg

    monkeypatch.setattr(job, "get_db", database)
    monkeypatch.setattr(job, "start_tracked_job", lambda *a, **kw: 1)
    monkeypatch.setattr(job, "finish_tracked_job", MagicMock())
    monkeypatch.setattr(job, "_run_impl", lambda **kw: {"status": "ok", "snapshots_built": 0})
    assert job.run(match_id=match["id"])["input_updates"]["completed"] == 2
    assert len(receipts(pg, match)) == 2


def test_runtime_filter_does_not_claim_other_fixture_heads(pg, match, ready):
    result = drain(pg, match, limit=1)
    assert result["claimed"] == 2
    assert query(
        pg,
        "SELECT DISTINCT match_id FROM prediction_input_consumers WHERE consumer_key=ANY(%s)",
        (list(runtime.CONSUMERS.values()),),
    )
    assert (
        query(
            pg,
            "SELECT match_id FROM prediction_input_consumers WHERE consumer_key=ANY(%s) "
            "AND match_id<>%s AND lease_token IS NOT NULL",
            (list(runtime.CONSUMERS.values()), match["id"]),
        )
        == []
    )


def test_terminal_completion_is_fenced_and_duplicate_receipt_is_immutable(
    pg, match, ready, consumer_factory
):
    from scripts.prediction_input_updates import claim_input_updates

    key = consumer_factory()
    query(pg, "UPDATE official_matches SET sale_status='closed' WHERE id=%s", (match["id"],))
    pg.commit()
    claim = claim_input_updates(pg, consumer_key=key, match_id=match["id"])[0]
    pg.commit()
    first = revisions.complete_blocked_prediction_input(pg, claim, play_type="spf")
    pg.commit()
    assert (
        revisions.complete_blocked_prediction_input(pg, claim, play_type="spf")["status"]
        == "already_completed"
    )
    assert (
        revisions.complete_blocked_prediction_input(pg, claim, play_type="spf")["result_refs"]
        == first["result_refs"]
    )
    pg.commit()
    query(pg, "UPDATE official_matches SET sale_status='selling' WHERE id=%s", (match["id"],))
    pg.commit()
    claim = claim_input_updates(pg, consumer_key=key, match_id=match["id"])[0]
    pg.commit()
    with pytest.raises(InputUpdateSuperseded, match="buildable"):
        revisions.complete_blocked_prediction_input(pg, claim, play_type="spf")
    pg.rollback()


def test_concurrent_default_consumers_publish_each_version_once(pg, match, ready, connect):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing

    pg.commit()

    def worker():
        with closing(connect()) as other:
            return runtime.drain_prediction_input_updates(other, match_id=match["id"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sum(r["completed"] for r in results) == 2
    assert all(r["failed"] == 0 for r in results)
    assert len(receipts(pg, match)) == 2


def test_fact_arriving_during_build_is_not_acknowledged_or_lost(pg, match, ready, connect):
    from contextlib import closing

    original = runtime.build_observed_feature_batch

    def build(*args, **kwargs):
        result = original(*args, **kwargs)
        with closing(connect()) as writer:
            prior.pipeline.weather(writer, match, effective_at=ready["kickoff"])
        return result

    with patch.object(runtime, "build_observed_feature_batch", side_effect=build):
        result = drain(pg, match)
    assert result["deferred"] == 2 and result["failed"] == 0
    assert receipts(pg, match) == []
    assert drain(pg, match)["completed"] == 2


def test_expired_readiness_is_refreshed_by_next_existing_task(pg, match, ready):
    import time

    original = runtime.complete_prediction_input_revision

    def complete(*args, **kwargs):
        return original(*args, **kwargs, max_age_seconds=1)

    with patch.object(runtime, "complete_prediction_input_revision", side_effect=complete):
        assert drain(pg, match)["completed"] == 2
    # Real database clock, no mutation of immutable retained history.
    time.sleep(1.1)
    assert drain(pg, match)["completed"] == 2
    assert len(receipts(pg, match)) == 4


def test_default_timeout_ceilings_restore_unbounded_session_on_commit(pg, match, ready):
    query(pg, "SET statement_timeout='0'")
    query(pg, "SET lock_timeout='0'")
    pg.commit()
    seen = []
    original = runtime.build_observed_feature_batch

    def build(*args, **kwargs):
        seen.append(
            (query(pg, "SHOW statement_timeout")[0][0], query(pg, "SHOW lock_timeout")[0][0])
        )
        return original(*args, **kwargs)

    with patch.object(runtime, "build_observed_feature_batch", side_effect=build):
        assert drain(pg, match)["completed"] == 2
    assert seen == [("5s", "500ms")] * 3
    assert query(pg, "SHOW statement_timeout") == [("0",)]
    assert query(pg, "SHOW lock_timeout") == [("0",)]


def test_claim_row_lock_timeout_defers_play_and_legacy_job_still_runs(
    pg, match, ready, connect, monkeypatch
):
    from contextlib import closing, contextmanager
    from unittest.mock import MagicMock

    from scripts.jobs import run_feature_snapshot_build as job

    key = runtime.CONSUMERS["spf"]
    query(
        pg,
        "INSERT INTO prediction_input_consumers(consumer_key,match_id) VALUES (%s,%s)",
        (key, match["id"]),
    )
    pg.commit()

    @contextmanager
    def database():
        yield pg

    legacy = MagicMock(return_value={"status": "ok", "snapshots_built": 1})
    monkeypatch.setattr(job, "get_db", database)
    monkeypatch.setattr(job, "start_tracked_job", lambda *a, **kw: 1)
    monkeypatch.setattr(job, "finish_tracked_job", MagicMock())
    monkeypatch.setattr(job, "_run_impl", legacy)
    with closing(connect()) as blocker:
        query(
            blocker,
            "SELECT match_id FROM prediction_input_consumers WHERE consumer_key=%s "
            "AND match_id=%s FOR UPDATE",
            (key, match["id"]),
        )
        result = job.run(match_id=match["id"])
        assert result["input_updates"]["deferred"] == 1
        assert result["input_updates"]["completed"] == 1
        assert result["input_updates"]["failed"] == 0
        assert result["status"] == "ok"
        legacy.assert_called_once()
        blocker.rollback()
    assert drain(pg, match)["completed"] == 1


def test_actual_claim_statement_timeout_is_deferred_not_raised(pg, match, ready):
    query(pg, "SET statement_timeout='50ms'")
    pg.commit()

    def slow_claim(*args, **kwargs):
        query(pg, "SELECT pg_sleep(0.1)")

    with patch.object(runtime, "claim_prediction_input_revisions", side_effect=slow_claim):
        result = drain(pg, match)
    assert result["deferred"] == 2 and result["failed"] == 0
    assert result["claimed"] == 0


def test_unexpected_claim_error_is_failed_and_other_play_still_runs(pg, match, ready):
    original = runtime.claim_prediction_input_revisions

    def claim(*args, **kwargs):
        if kwargs["consumer_key"] == runtime.CONSUMERS["spf"]:
            raise RuntimeError("fixture")
        return original(*args, **kwargs)

    with patch.object(runtime, "claim_prediction_input_revisions", side_effect=claim):
        result = drain(pg, match)
    assert result["status"] == "failed" and result["failed"] == 1
    assert result["completed"] == 1
    assert result["errors"][0]["phase"] == "claim"
