"""Complete builder -> immutable batch -> shared model input on owned PG fixtures."""

from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from scripts import observed_feature_pipeline as pipeline
from scripts.data_catalog import get_field_resolution_policy
from scripts.data_contracts import FactStatus
from scripts.feature_batch_storage import load_feature_batch, store_feature_batch
from scripts.feature_schema import FEATURE_COLUMNS
from scripts.jobs.run_feature_snapshot_build import build_observed_feature_batch
from scripts.observation_storage import append_observation, capture_observation_cutoff
from scripts.prematch_feature_dataset import load_observed_feature_input
from tests.test_computation import test_observation_postgres as obs
from tests.test_computation import test_player_observations_postgres as players

connect = obs.connect
pg = obs.pg
match_id = obs.match_id
match = players.match
KICKOFF = datetime(2026, 11, 1, 12, tzinfo=UTC)


def context(match):
    return dict(
        home_team_id=match["home_team_id"],
        away_team_id=match["away_team_id"],
        kickoff_at=KICKOFF.isoformat(),
    )


def freeze(pg, match):
    streams = [
        dict(match_id=match["id"], source_id="open_meteo", domain="weather", subject_key="forecast")
    ]
    streams += [
        dict(
            match_id=match["id"],
            source_id="api_football",
            domain=domain,
            subject_key=f"team:{match[side + '_team_id']}",
        )
        for domain in ("lineup", "injuries")
        for side in ("home", "away")
    ]
    cut = capture_observation_cutoff(pg, streams=streams)
    pg.commit()
    return cut


def weather(pg, match, value=0, **changes):
    at = datetime.now(UTC) - timedelta(seconds=1)
    args = dict(
        match_id=match["id"],
        source_id="open_meteo",
        domain="weather",
        subject_key="forecast",
        fact_status=FactStatus.VALUE,
        value={"temperature_2m": value},
        acquired_at=at,
        verified_at=at,
        effective_at=KICKOFF,
        valid_until=at + timedelta(hours=6),
    )
    args.update(changes)
    if args["fact_status"] != FactStatus.VALUE:
        args["value"] = None
    append_observation(pg, **args)
    pg.commit()


def publish(pg, match, cutoff=None):
    cut = cutoff or freeze(pg, match)
    identifier = build_observed_feature_batch(
        pg, match_id=match["id"], cutoff=cut, context=context(match)
    )
    return identifier, cut


def read(pg, match, identifier, cut, **changes):
    args = dict(
        batch_id=identifier,
        match_id=match["id"],
        as_of=cut.as_of,
        feature_columns=("away_lineup_confirmed", "temperature_2m", "home_lineup_confirmed"),
        required_fields=("temperature_2m",),
    )
    args.update(changes)
    return load_observed_feature_input(pg, **args)


def test_full_55_fields_share_one_cutoff_and_keep_unknowns(pg, match):
    weather(pg, match)
    identifier, cut = publish(pg, match)
    pg.commit()
    batch = load_feature_batch(pg, identifier)
    assert batch["required_fields"] == list(FEATURE_COLUMNS)
    assert set(batch["features"]) == set(FEATURE_COLUMNS)
    assert batch["cutoff"] == cut
    for field in (
        "home_key_absence_count",
        "data_completeness_score",
        "home_attack_strength_score",
    ):
        assert batch["features"][field]["value"] is None
        assert batch["features"][field]["fact_status"] == "unknown"
    assert batch["features"]["temperature_2m"]["value"] == 0
    result = read(pg, match, identifier, cut)
    assert result["status"] == "ready"
    assert result["values"] == [None, 0.0, None]
    assert result["batch_id"] == identifier and result["cutoff_id"] == cut.id
    assert result["snapshot"]["home_key_absence_count"] is None


def test_batch_visibility_is_atomic_and_rollback_leaves_no_input(pg, connect, match):
    weather(pg, match)
    cut = freeze(pg, match)
    identifier, _ = publish(pg, match, cut)
    with closing(connect()) as other:
        assert read(other, match, identifier, cut)["status"] == "no_complete_batch"
    pg.rollback()
    assert read(pg, match, identifier, cut)["status"] == "no_complete_batch"
    identifier, _ = publish(pg, match, cut)
    pg.commit()
    with closing(connect()) as other:
        assert read(other, match, identifier, cut)["status"] == "ready"


def test_same_batch_replays_after_source_correction_and_catalog_policy_change(pg, match):
    weather(pg, match)
    identifier, cut = publish(pg, match)
    pg.commit()
    before = read(pg, match, identifier, cut)
    weather(pg, match, 28)
    changed = get_field_resolution_policy("weather.temperature_2m")
    changed["version"] = "changed/v2"
    changed["max_age_seconds"] = 1
    with (
        patch("scripts.observation_resolution.get_field_resolution_policy", return_value=changed),
        patch.object(pipeline, "get_field_resolution_policy", return_value=changed),
    ):
        assert read(pg, match, identifier, cut) == before
    newer, newcut = publish(pg, match)
    pg.commit()
    assert read(pg, match, newer, newcut)["values"][1] == 28


def test_missing_source_stays_missing_and_blocks_required_input(pg, match):
    identifier, cut = publish(pg, match)
    pg.commit()
    weather(pg, match)
    result = read(pg, match, identifier, cut)
    assert result["status"] == "insufficient_inputs" and result["snapshot"] is None
    assert result["missing_required_fields"] == ["temperature_2m"]
    assert result["values"] == [None, None, None]


def test_predicted_later_freshness_does_not_change_original_batch(pg, match):
    weather(pg, match)
    identifier, cut = publish(pg, match)
    pg.commit()
    before = load_feature_batch(pg, identifier)
    result = read(pg, match, identifier, cut, as_of=cut.as_of + timedelta(hours=7))
    assert result["status"] == "insufficient_inputs"
    assert result["field_statuses"]["temperature_2m"] == "stale"
    assert load_feature_batch(pg, identifier) == before


@pytest.mark.parametrize("at", ["naive", "before", "kickoff"])
def test_prediction_time_requires_aware_cutoff_to_kickoff_window(pg, match, at):
    weather(pg, match)
    identifier, cut = publish(pg, match)
    pg.commit()
    value = {
        "naive": datetime(2026, 10, 20),
        "before": cut.as_of - timedelta(seconds=1),
        "kickoff": KICKOFF,
    }[at]
    with pytest.raises(ValueError, match="time"):
        read(pg, match, identifier, cut, as_of=value)


def test_wrong_match_never_reads_another_match_or_latest(pg, match):
    weather(pg, match)
    identifier, cut = publish(pg, match)
    pg.commit()
    with pytest.raises(ValueError, match="match"):
        read(pg, match, identifier, cut, match_id=match["id"] + 1)


def test_future_forecast_for_another_kickoff_is_not_reused(pg, match):
    weather(pg, match, effective_at=KICKOFF + timedelta(days=1))
    identifier, cut = publish(pg, match)
    pg.commit()
    result = read(pg, match, identifier, cut)
    assert result["status"] == "insufficient_inputs"
    assert result["field_statuses"]["temperature_2m"] == "unknown"


def test_actual_lineup_adapter_reaches_shared_model_input_without_heuristic_scores(pg, match):
    from scripts.jobs.collect_lineup_data import _process_lineup

    _process_lineup(
        pg,
        match["id"],
        players.lineup(),
        match["home_team_id"],
        datetime.now(UTC),
        api_fixture_id=900,
    )
    weather(pg, match)
    identifier, cut = publish(pg, match)
    pg.commit()
    result = read(pg, match, identifier, cut)
    assert result["values"] == [None, 0.0, True]
    assert result["snapshot"]["home_lineup_strength_score"] is None
    from scripts.logistic_shadow_model import LogisticShadowProfile, probabilities_from_classifier

    classifier = MagicMock()
    classifier.classes_ = [0, 1, 2]
    classifier.predict_proba.return_value = [[0.2, 0.3, 0.5]]
    profile = LogisticShadowProfile("unused", tuple(result["feature_columns"]), 100, 25, 1.0)
    assert probabilities_from_classifier(classifier, profile, result["snapshot"]) == {
        "0": 0.2,
        "1": 0.3,
        "3": 0.5,
    }
    inputs = classifier.predict_proba.call_args.args[0][0]
    assert inputs[1:] == [0.0, 1.0]
    assert inputs[0] != inputs[0]  # Unknown stays NaN in the existing numeric boundary.


def test_old_artifact_policy_does_not_automatically_accept_pilot(pg, match):
    from scripts.feature_schema import FEATURE_INPUT_POLICY, FEATURE_SCHEMA_VERSION
    from scripts.shadow_model_helpers import prepare_shadow_input

    weather(pg, match)
    identifier, cut = publish(pg, match)
    pg.commit()
    snapshot = read(pg, match, identifier, cut)["snapshot"]
    parameters = dict(
        feature_input_policy=FEATURE_INPUT_POLICY,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_columns=["temperature_2m"],
    )
    assert prepare_shadow_input(parameters, snapshot) is None


@pytest.mark.parametrize("damage", ["value", "value_type", "context", "policy_hash", "reason"])
def test_even_rehashed_batch_must_match_named_derivation(pg, match, damage):
    weather(pg, match)
    identifier, cut = publish(pg, match)
    pg.commit()
    data = deepcopy(load_feature_batch(pg, identifier)["features"])
    field = data["temperature_2m"]
    if damage == "value":
        field["value"] = 60
    if damage == "value_type":
        field["value"] = False
    if damage == "context":
        field["derivation"]["context"]["away_team_id"] += 100
    if damage == "policy_hash":
        field["derivation"]["resolution"]["policy_hash"] = "0" * 64
    if damage == "reason":
        data["home_attack_strength_score"]["derivation"]["reason"] = "made_up"
        data["home_attack_strength_score"]["observation_indexes"] = [0]
    forged = store_feature_batch(
        pg,
        match_id=match["id"],
        cutoff=cut,
        builder_version=pipeline.BUILDER_VERSION,
        required_fields=FEATURE_COLUMNS,
        features=data,
    )
    pg.commit()
    with pytest.raises(ValueError):
        read(pg, match, forged, cut)


def test_legacy_batch_is_explicitly_unreplayable_by_pilot(pg, match):
    weather(pg, match)
    cut = freeze(pg, match)
    identifier = store_feature_batch(
        pg,
        match_id=match["id"],
        cutoff=cut,
        builder_version="old/v1",
        required_fields=("temperature_2m",),
        features={"temperature_2m": dict(fact_status="value", value=0, observation_indexes=[0])},
    )
    pg.commit()
    assert read(pg, match, identifier, cut)["status"] == "unsupported_batch_contract"


def test_reader_role_is_read_only_and_does_not_publish(pg, match):
    weather(pg, match)
    identifier, cut = publish(pg, match)
    pg.commit()
    with pg.cursor() as q:
        q.execute("SET TRANSACTION READ ONLY")
        q.execute("SET LOCAL ROLE fqp_observation_reader")
    assert read(pg, match, identifier, cut)["status"] == "ready"
    pg.rollback()


@pytest.mark.parametrize(
    "status",
    [
        FactStatus.UNKNOWN,
        FactStatus.NOT_PUBLISHED,
        FactStatus.NOT_COVERED,
        FactStatus.CONFLICT,
        FactStatus.NOT_APPLICABLE,
    ],
)
def test_nonvalue_source_states_remain_explained_not_zero(pg, match, status):
    weather(pg, match, fact_status=status, value=None)
    identifier, cut = publish(pg, match)
    pg.commit()
    result = read(pg, match, identifier, cut)
    assert result["status"] == "insufficient_inputs"
    assert result["field_statuses"]["temperature_2m"] == status.value
    assert result["values"][1] is None


def test_old_success_is_stale_even_without_source_valid_until(pg, match):
    past = datetime.now(UTC) - timedelta(hours=8)
    weather(pg, match, acquired_at=past, verified_at=past, valid_until=None)
    identifier, cut = publish(pg, match)
    pg.commit()
    assert read(pg, match, identifier, cut)["field_statuses"]["temperature_2m"] == "stale"


def test_covered_empty_injuries_do_not_imply_key_absence_count(pg, match):
    at = datetime.now(UTC) - timedelta(seconds=1)
    append_observation(
        pg,
        match_id=match["id"],
        source_id="api_football",
        domain="injuries",
        subject_key=f"team:{match['home_team_id']}",
        fact_status=FactStatus.CONFIRMED_ABSENT,
        value=None,
        acquired_at=at,
        verified_at=at,
        evidence={"coverage_complete": True, "coverage_evidence": "fixed-local-evidence"},
    )
    pg.commit()
    identifier, cut = publish(pg, match)
    pg.commit()
    feature = load_feature_batch(pg, identifier)["features"]["home_key_absence_count"]
    assert feature["value"] is None and feature["fact_status"] == "unknown"
    assert feature["derivation"]["resolution"]["fact_status"] == "confirmed_absent"
    assert feature["derivation"]["reason"] == "no_key_player_derivation"


def test_cannot_omit_a_policy_source_or_research_cutoff(pg, match):
    from dataclasses import replace

    weather(pg, match)
    cut = capture_observation_cutoff(
        pg,
        streams=[
            dict(
                match_id=match["id"],
                source_id="open_meteo",
                domain="weather",
                subject_key="forecast",
            )
        ],
    )
    pg.commit()
    with pytest.raises(ValueError, match="declared"):
        publish(pg, match, cut)
    with pytest.raises(ValueError, match="runtime"):
        publish(pg, match, replace(cut, include_reconstruction=True))


def test_all_missing_optional_columns_are_ready_only_for_explicit_empty_requirements(pg, match):
    identifier, cut = publish(pg, match)
    pg.commit()
    result = read(pg, match, identifier, cut, required_fields=())
    assert result["status"] == "ready" and result["values"] == [None, None, None]
    assert result["missing_required_fields"] == []


def test_expiry_boundary_is_inclusive_and_uses_only_frozen_success(pg, match):
    weather(pg, match)
    identifier, cut = publish(pg, match)
    pg.commit()
    feature = load_feature_batch(pg, identifier)["features"]["temperature_2m"]
    expiry = datetime.fromisoformat(
        feature["derivation"]["resolution"]["candidates"][0]["expires_at"]
    )
    weather(pg, match, 25)  # Later refresh must not prolong an earlier batch.
    assert (
        read(pg, match, identifier, cut, as_of=expiry - timedelta(microseconds=1))["status"]
        == "ready"
    )
    assert (
        read(pg, match, identifier, cut, as_of=expiry)["field_statuses"]["temperature_2m"]
        == "stale"
    )


@pytest.mark.parametrize("metadata", [None, {}, "not-an-object", {"large": "x" * 33000}])
def test_optional_derivation_metadata_is_bounded_and_never_null(pg, match, metadata):
    weather(pg, match)
    identifier, cut = publish(pg, match)
    pg.commit()
    data = load_feature_batch(pg, identifier)["features"]
    data["temperature_2m"]["derivation"] = metadata
    with pytest.raises(ValueError):
        store_feature_batch(
            pg,
            match_id=match["id"],
            cutoff=cut,
            builder_version=pipeline.BUILDER_VERSION,
            required_fields=FEATURE_COLUMNS,
            features=data,
        )
