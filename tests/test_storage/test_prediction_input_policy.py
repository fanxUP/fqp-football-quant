"""Fixed local inputs for model selection; no provider, artifact load or database."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from scripts.feature_schema import FEATURE_COLUMNS
from scripts.observed_feature_pipeline import BUILDER_VERSION
from scripts.prediction_input_policy import (
    InputProfile,
    PredictionContext,
    load_prediction_input_mode,
    select_prediction_input_mode,
)

AT = datetime(2026, 11, 1, 10, tzinfo=UTC)


def context(**changes):
    return replace(
        PredictionContext(
            match_id=7,
            play_type="spf",
            decision_at=AT,
            kickoff_at=AT + timedelta(hours=2),
            sale_stop_at=AT + timedelta(hours=1),
            identity_verified=True,
            sale_status="selling",
            match_status="scheduled",
            market_open=True,
            odds_by_option={"3": 2.0, "1": 3.5, "0": 4.0},
            odds_snapshot_ids={"3": 11, "1": 12, "0": 13},
        ),
        **changes,
    )


def profile(**changes):
    return replace(
        InputProfile(
            profile_id="basic-v1",
            model_name="logistic_shadow",
            model_version_id=4,
            mode="basic",
            feature_versions=(BUILDER_VERSION,),
            feature_columns=("temperature_2m",),
            required_fields=("temperature_2m",),
            validation_reference="fixed-fixture-validation/v1",
            artifact_ready=True,
            independent=True,
            rollout_mode="live",
        ),
        **changes,
    )


def batch(*, values=None, statuses=None, at=AT):
    fields = dict.fromkeys(FEATURE_COLUMNS)
    fields.update(values or {"temperature_2m": 0.0})
    states = {f: "unknown" if value is None else "value" for f, value in fields.items()}
    states.update(statuses or {})
    return dict(
        status="ready",
        match_id=7,
        batch_id=21,
        cutoff_id="00000000-0000-0000-0000-000000000001",
        as_of=at.isoformat(),
        feature_columns=list(FEATURE_COLUMNS),
        values=list(fields.values()),
        field_statuses=states,
        snapshot=dict(
            fields,
            feature_version=BUILDER_VERSION,
            feature_batch_id=21,
            observation_cutoff_id="00000000-0000-0000-0000-000000000001",
        ),
    )


def choose(profiles=None, data=None, ctx=None):
    return select_prediction_input_mode(
        context=ctx or context(),
        feature_input=data if data is not None else batch(),
        profiles=profiles if profiles is not None else (profile(),),
    )


def test_unpublished_lineup_and_failed_injury_source_allow_validated_basic_input():
    enhanced = profile(
        profile_id="enhanced-v1",
        mode="enhanced",
        feature_columns=("temperature_2m", "home_lineup_confirmed", "away_key_absence_count"),
        required_fields=("temperature_2m", "home_lineup_confirmed", "away_key_absence_count"),
    )
    data = batch(
        statuses={"home_lineup_confirmed": "not_published", "away_key_absence_count": "unknown"}
    )
    before = deepcopy(data)
    result = choose((enhanced, profile()), data)
    assert result["mode"] == "basic"
    assert result["profile_id"] == "basic-v1"
    assert result["recommendation_eligible"] is True
    assert result["excluded_profiles"]["enhanced-v1"] == "missing_required_fields"
    assert result["values"] == [0.0]
    assert result["feature_version"] == BUILDER_VERSION
    assert result["field_statuses"]["home_lineup_confirmed"] == "not_published"
    result["field_statuses"]["home_lineup_confirmed"] = "value"
    assert data == before


def test_one_side_confirmed_is_not_both_sides_and_does_not_abort_selection():
    enhanced = profile(
        profile_id="both-lineups",
        mode="enhanced",
        feature_columns=("home_lineup_confirmed", "away_lineup_confirmed"),
        required_fields=("home_lineup_confirmed", "away_lineup_confirmed"),
    )
    result = choose(
        (enhanced, profile()),
        batch(values={"home_lineup_confirmed": True, "temperature_2m": 12}),
    )
    assert result["mode"] == "basic"
    assert result["excluded_profiles"]["both-lineups"] == "missing_required_fields"


def test_ready_enhanced_input_precedes_basic_without_changing_ordered_values():
    enhanced = profile(
        profile_id="enhanced-v1",
        mode="enhanced",
        feature_columns=("home_lineup_confirmed", "temperature_2m"),
        required_fields=("home_lineup_confirmed", "temperature_2m"),
    )
    result = choose(
        (profile(), enhanced), batch(values={"temperature_2m": 0, "home_lineup_confirmed": False})
    )
    assert result["mode"] == "enhanced"
    assert result["values"] == [False, 0]
    assert type(result["values"][0]) is bool
    assert result["feature_batch_id"] == 21
    assert result["observation_cutoff_id"].endswith("000001")


def test_optional_missing_requires_exact_validated_pattern_and_never_fills_zero():
    candidate = profile(
        feature_columns=("temperature_2m", "home_lineup_confirmed"),
        required_fields=("temperature_2m",),
    )
    rejected = choose((candidate,))
    assert rejected["mode"] == "market_reference"
    assert rejected["excluded_profiles"][candidate.profile_id] == "unvalidated_missing_pattern"
    accepted = choose(
        (replace(candidate, validated_missing_patterns=(("home_lineup_confirmed",),)),)
    )
    assert accepted["mode"] == "basic"
    assert accepted["values"] == [0.0, None]
    assert accepted["missing_fields"] == ["home_lineup_confirmed"]


def test_all_missing_inputs_cannot_masquerade_as_an_independent_signal():
    candidate = profile(required_fields=(), validated_missing_patterns=(("temperature_2m",),))
    result = choose((candidate,), batch(values={"temperature_2m": None}))
    assert result["mode"] == "market_reference"
    assert result["excluded_profiles"]["basic-v1"] == "no_observed_model_fields"


@pytest.mark.parametrize(
    "status",
    [
        "unknown",
        "not_published",
        "not_covered",
        "confirmed_absent",
        "conflict",
        "stale",
        "not_applicable",
    ],
)
def test_non_value_status_cannot_become_required_numeric_zero(status):
    data = batch(values={"temperature_2m": None}, statuses={"temperature_2m": status})
    assert choose(data=data)["mode"] == "market_reference"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"validation_reference": None}, "validation_unavailable"),
        ({"artifact_ready": False}, "artifact_unavailable"),
        ({"independent": False}, "non_independent_profile"),
        ({"feature_versions": ("v4_observed_form",)}, "incompatible_feature_version"),
    ],
)
def test_validation_artifact_independence_and_version_are_separate_gates(changes, reason):
    result = choose((profile(**changes),))
    assert result["mode"] == "market_reference"
    assert result["model_independent"] is False
    assert result["model_name"] is None
    assert result["recommendation_eligible"] is False
    assert result["excluded_profiles"]["basic-v1"] == reason


@pytest.mark.parametrize(
    "changes,restriction",
    [
        ({"identity_verified": False}, "official_identity_unverified"),
        ({"sale_stop_at": None}, "sale_deadline_unknown"),
        ({"sale_stop_at": AT}, "sale_closed"),
        ({"sale_status": "stopped"}, "sale_closed"),
        ({"market_open": False}, "market_closed"),
        ({"kickoff_at": AT}, "kickoff_reached"),
        ({"match_status": "postponed"}, "match_not_scheduled"),
    ],
)
def test_business_restrictions_only_limit_current_match_and_market(changes, restriction):
    result = choose(ctx=context(**changes))
    assert result["recommendation_eligible"] is False
    assert restriction in result["restrictions"]
    assert choose()["recommendation_eligible"] is True


def test_live_basic_precedes_shadow_enhanced_and_shadow_stays_research_only():
    shadow = profile(profile_id="enhanced-shadow", mode="enhanced", rollout_mode="shadow")
    assert choose((shadow, profile()))["profile_id"] == "basic-v1"
    result = choose((shadow,))
    assert result["mode"] == "enhanced"
    assert result["recommendation_eligible"] is False
    assert "shadow_only" in result["restrictions"]


def test_unsupported_model_market_does_not_relabel_spf_as_handicap():
    result = choose(ctx=context(play_type="rqspf", handicap=-1.0))
    assert result["mode"] == "market_reference"
    assert result["excluded_profiles"]["basic-v1"] == "unsupported_market"


@pytest.mark.parametrize(
    "changes",
    [
        {"odds_by_option": {"3": 2.0}},
        {"odds_by_option": {"3": float("nan"), "1": 3.5, "0": 4.0}},
        {"odds_by_option": {"3": True, "1": 3.5, "0": 4.0}},
        {"odds_snapshot_ids": {"3": 11, "1": 11, "0": 13}},
        {"odds_snapshot_ids": {"3": True, "1": 12, "0": 13}},
    ],
)
def test_incomplete_or_invalid_market_gives_pending_without_an_independent_model(changes):
    result = choose((), ctx=context(**changes))
    assert result["mode"] == "awaiting_verification"
    assert result["recommendation_eligible"] is False
    assert "invalid_official_market" in result["restrictions"]


def test_invalid_market_keeps_qualified_input_for_research_without_advice():
    result = choose(ctx=context(odds_by_option={}))
    assert result["mode"] == "basic"
    assert result["recommendation_eligible"] is False


@pytest.mark.parametrize(
    "data", [None, {"status": "no_complete_batch"}, {"status": "unsupported_batch_contract"}]
)
def test_missing_or_incompatible_batch_does_not_stop_market_reference(data):
    result = select_prediction_input_mode(
        context=context(), feature_input=data, profiles=(profile(),)
    )
    assert result["mode"] == "market_reference"
    assert not result["recommendation_eligible"]


def test_old_as_of_cannot_extend_freshness_or_restore_recommendation():
    result = choose(data=batch(at=AT - timedelta(minutes=31)))
    assert result["mode"] == "market_reference"
    assert result["excluded_profiles"]["basic-v1"] == "input_time_mismatch"


def test_future_input_cannot_be_used_for_an_earlier_decision():
    result = choose(data=batch(at=AT + timedelta(seconds=1)))
    assert result["mode"] == "market_reference"
    assert result["excluded_profiles"]["basic-v1"] == "input_time_mismatch"


@pytest.mark.parametrize(
    "changes",
    [
        {"decision_at": AT.replace(tzinfo=None)},
        {"sale_stop_at": AT.replace(tzinfo=None)},
        {"match_id": True},
    ],
)
def test_context_does_not_guess_timezone_or_coerce_official_identity(changes):
    with pytest.raises(ValueError):
        context(**changes)


def test_same_instant_in_beijing_is_normalized_without_changing_expiry():
    from zoneinfo import ZoneInfo

    result = choose(ctx=context(decision_at=AT.astimezone(ZoneInfo("Asia/Shanghai"))))
    assert result["recommendation_eligible"] is True
    assert result["as_of"] == AT.isoformat()


def test_batch_from_another_match_is_rejected_before_model_selection():
    data = batch()
    data["match_id"] = 8
    with pytest.raises(ValueError, match="another match"):
        choose(data=data)


@pytest.mark.parametrize(
    "change", ["vector", "status", "bool", "batch_id", "cutoff_id", "non_finite"]
)
def test_inconsistent_batch_is_rejected_without_casting_or_filling(change):
    data = batch()
    if change == "vector":
        data["values"][FEATURE_COLUMNS.index("temperature_2m")] = 5
    elif change == "status":
        data["field_statuses"]["temperature_2m"] = "unknown"
    elif change == "bool":
        data["snapshot"]["temperature_2m"] = False
    elif change == "batch_id":
        data["snapshot"]["feature_batch_id"] = 99
    elif change == "cutoff_id":
        data["snapshot"]["observation_cutoff_id"] = "other-cutoff"
    else:
        data["snapshot"]["temperature_2m"] = float("inf")
        data["values"][FEATURE_COLUMNS.index("temperature_2m")] = float("inf")
    result = choose(data=data)
    assert result["mode"] == "market_reference"
    assert result["excluded_profiles"]["basic-v1"] == "invalid_input_contract"


def test_explicit_loader_reads_one_complete_batch_and_never_commits():
    conn = MagicMock()
    profiles = (profile(), profile(profile_id="other", mode="enhanced"))
    with patch(
        "scripts.observed_feature_pipeline.load_observed_feature_input", return_value=batch()
    ) as read:
        result = load_prediction_input_mode(conn, batch_id=21, context=context(), profiles=profiles)
    assert result["mode"] == "enhanced"
    read.assert_called_once_with(
        conn, batch_id=21, match_id=7, as_of=AT, feature_columns=FEATURE_COLUMNS, required_fields=()
    )
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()


def test_post_kickoff_loader_keeps_research_boundary_without_runtime_batch_read():
    conn = MagicMock()
    result = load_prediction_input_mode(
        conn, batch_id=21, context=context(kickoff_at=AT), profiles=(profile(),)
    )
    assert result["mode"] == "market_reference"
    assert not result["recommendation_eligible"]
    assert "kickoff_reached" in result["restrictions"]
    conn.cursor.assert_not_called()


def test_sale_closed_input_remains_readable_for_research_before_kickoff():
    conn = MagicMock()
    with patch(
        "scripts.observed_feature_pipeline.load_observed_feature_input", return_value=batch()
    ) as read:
        result = load_prediction_input_mode(
            conn, batch_id=21, context=context(sale_stop_at=AT), profiles=(profile(),)
        )
    assert result["mode"] == "basic"
    assert result["recommendation_eligible"] is False
    assert "sale_closed" in result["restrictions"]
    read.assert_called_once()


def test_no_profiles_need_no_batch_read_to_provide_market_reference():
    conn = MagicMock()
    result = load_prediction_input_mode(conn, batch_id=21, context=context(), profiles=())
    assert result["mode"] == "market_reference"
    conn.cursor.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"model_version_id": True},
        {"required_fields": ("home_lineup_confirmed",)},
        {"validated_missing_patterns": (("temperature_2m",),)},
        {"feature_columns": ("not_a_feature",)},
        {"artifact_ready": "yes"},
        {"rollout_mode": "arbitrary"},
    ],
)
def test_invalid_internal_profiles_fail_before_database(changes):
    with pytest.raises(ValueError):
        profile(**changes)


def test_profile_limits_and_duplicate_ids_are_rejected_before_read():
    conn = MagicMock()
    for profiles in ((profile(), profile()), tuple(profile(profile_id=str(i)) for i in range(17))):
        with pytest.raises(ValueError):
            load_prediction_input_mode(conn, batch_id=21, context=context(), profiles=profiles)
    conn.cursor.assert_not_called()


def test_shared_dataset_entry_delegates_to_policy_with_explicit_context():
    from scripts.prematch_feature_dataset import load_prediction_input_mode as shared_load

    conn = MagicMock()
    args = dict(batch_id=21, context=context(), profiles=(profile(),))
    with patch(
        "scripts.prediction_input_policy.load_prediction_input_mode", return_value={"mode": "basic"}
    ) as read:
        assert shared_load(conn, **args) == {"mode": "basic"}
        read.assert_called_once_with(conn, **args)
