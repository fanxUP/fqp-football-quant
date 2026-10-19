"""Fixed resolver policies and frozen records; no HTTP or application database."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from scripts.data_contracts import FactStatus
from scripts.observation_resolution import resolve_observed_field
from scripts.observation_storage import ObservationCutoff

AT = datetime(2026, 10, 19, 8, tzinfo=UTC)
CUTOFF = ObservationCutoff("00b11111-1111-4111-8111-111111111111", AT)


def policy(**changes):
    value = dict(
        version="observation-fields/v1",
        field="weather.temperature_2m",
        domain="weather",
        subject="forecast",
        extractor="temperature_2m/v1",
        max_age_seconds=21600,
        sources={"open_meteo": 10},
    )
    return {**value, **changes}


def candidate(source="open_meteo", value=0, **changes):
    ref = dict(
        match_id=1,
        source_id=source,
        source_family=source,
        domain="weather",
        subject_key="forecast",
        revision_id=1,
        latest_check_id=2,
        freshness_check_id=2,
    )
    obs = dict(
        revision_id=1,
        content_hash="a" * 64,
        fact_status="value",
        original_fact_status="value",
        value={"temperature_2m": value},
        evidence={},
        evidence_kind="source_observation",
        acquisition_status="success",
        valid_until=AT + timedelta(hours=1),
        last_success_acquired_at=AT - timedelta(minutes=1),
        available_at=AT - timedelta(minutes=1),
        effective_at=AT + timedelta(hours=8),
    )
    obs.update(changes)
    return ref, obs


def resolve(items=None, rule=None, **changes):
    items = items or [candidate()]
    refs, obs = map(list, zip(*items, strict=True))
    conn = MagicMock()
    args = dict(match_id=1, subject_key="forecast", field="weather.temperature_2m", cutoff=CUTOFF)
    args.update(changes)
    with (
        patch("scripts.observation_resolution.load_observation_selection", return_value=refs),
        patch("scripts.observation_resolution.load_cutoff_observations", return_value=obs),
    ):
        result = resolve_observed_field(conn, **args, policy=rule or policy())
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    conn.cursor.assert_not_called()
    return result


def test_zero_is_a_real_value_and_policy_snapshot_is_isolated():
    rule = policy()
    result = resolve(rule=rule)
    assert result["fact_status"] == "value" and result["value"] == 0
    assert result["selected_indexes"] == [0]
    assert result["candidates"][0]["revision_id"] == 1
    assert len(result["policy_hash"]) == 64
    rule["sources"]["open_meteo"] = 99
    assert result["policy"]["sources"]["open_meteo"] == 10


def test_same_rank_different_values_conflict_without_average():
    result = resolve(
        [candidate(value=5), candidate("api_football", 15)],
        policy(sources={"open_meteo": 10, "api_football": 10}),
    )
    assert result["fact_status"] == "conflict"
    assert result["value"] is None and result["selected_indexes"] == []
    assert [c["value"] for c in result["candidates"]] == [5, 15]


@pytest.mark.parametrize("value", [0.0, -0.0])
def test_same_numeric_claim_has_one_temperature_representation(value):
    result = resolve(
        [candidate(value=0), candidate("api_football", value)],
        policy(sources={"open_meteo": 10, "api_football": 10}),
    )
    assert result["fact_status"] == "value" and result["selected_indexes"] == [0, 1]


def test_different_forecast_targets_do_not_agree_just_because_temperature_matches():
    result = resolve(
        [candidate(), candidate("api_football", effective_at=AT + timedelta(hours=9))],
        policy(sources={"open_meteo": 10, "api_football": 10}),
    )
    assert result["fact_status"] == "conflict" and result["value"] is None


def test_forecast_without_explicit_business_target_is_not_usable():
    assert resolve([candidate(effective_at=None)])["fact_status"] == "unknown"


@pytest.mark.parametrize("same_family", [False, True])
def test_lower_rank_majority_and_reposts_do_not_overrule_field_authority(same_family):
    items = [candidate(value=5), candidate("api_football", 15), candidate("newsapi", 15)]
    if same_family:
        items[1][0]["source_family"] = items[2][0]["source_family"] = "repost_origin"
    result = resolve(items, policy(sources={"open_meteo": 1, "api_football": 10, "newsapi": 10}))
    assert result["value"] == 5 and result["selected_indexes"] == [0]
    assert all(c["reason"] == "lower_authority" for c in result["candidates"][1:])
    assert result["disagreement_indexes"] == [1, 2]


def test_agreeing_same_family_is_one_family_and_all_citations_remain():
    items = [candidate(), candidate("api_football")]
    items[1][0]["source_family"] = "open_meteo"
    result = resolve(items, policy(sources={"open_meteo": 10, "api_football": 10}))
    assert result["selected_indexes"] == [0, 1]
    assert result["selected_family_count"] == 1


def test_same_family_inconsistent_claims_are_still_conflict():
    items = [candidate(value=1), candidate("api_football", 2)]
    items[1][0]["source_family"] = "open_meteo"
    assert (
        resolve(items, policy(sources={"open_meteo": 10, "api_football": 10}))["fact_status"]
        == "conflict"
    )


def test_field_rank_can_choose_another_source_without_global_reputation():
    items = [candidate(value=1), candidate("api_football", 2)]
    result = resolve(items, policy(sources={"open_meteo": 10, "api_football": 1}))
    assert result["value"] == 2 and result["selected_indexes"] == [1]


@pytest.mark.parametrize(
    "changes",
    [
        {"valid_until": AT},
        {"valid_until": None, "last_success_acquired_at": AT - timedelta(hours=6)},
        {
            "valid_until": AT + timedelta(days=1),
            "last_success_acquired_at": AT - timedelta(hours=7),
        },
    ],
)
def test_either_expiry_boundary_makes_value_stale(changes):
    result = resolve([candidate(**changes)])
    assert result["fact_status"] == "stale" and result["value"] is None
    assert result["candidates"][0]["reason"] == "stale"


def test_no_explicit_expiry_still_has_bounded_field_policy():
    assert resolve([candidate(valid_until=None)])["value"] == 0


def test_fresh_lower_authority_can_fill_stale_primary_with_reasons():
    result = resolve(
        [candidate(valid_until=AT), candidate("api_football", 7)],
        policy(sources={"open_meteo": 1, "api_football": 10}),
    )
    assert result["value"] == 7 and result["selected_indexes"] == [1]
    assert result["candidates"][0]["reason"] == "stale"


def test_source_explicit_conflict_cannot_be_silently_replaced_by_lower_authority():
    result = resolve(
        [
            candidate(original_fact_status="conflict", fact_status="conflict", value=None),
            candidate("api_football", 7),
        ],
        policy(sources={"open_meteo": 1, "api_football": 10}),
    )
    assert result["fact_status"] == "conflict" and result["value"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"last_success_acquired_at": None},
        {"last_success_acquired_at": AT.replace(tzinfo=None)},
        {"last_success_acquired_at": AT + timedelta(seconds=1)},
        {"available_at": AT + timedelta(seconds=1)},
        {"valid_until": AT.replace(tzinfo=None)},
    ],
)
def test_invalid_or_future_timing_is_not_usable(changes):
    result = resolve([candidate(**changes)])
    assert result["fact_status"] == "unknown" and result["value"] is None
    assert result["candidates"][0]["reason"] == "invalid_timing"


def test_citations_use_original_cutoff_indices_after_scope_filtering():
    unrelated = candidate("api_football", 50)
    unrelated[0]["match_id"] = 2
    result = resolve([unrelated, candidate(value=3)])
    assert result["selected_indexes"] == [1]
    assert result["candidates"][0]["index"] == 1


@pytest.mark.parametrize("status", ["failed", "quota_exhausted", "forbidden", "unavailable"])
def test_failure_does_not_erase_still_fresh_fact_or_refresh_its_age(status):
    result = resolve([candidate(acquisition_status=status)])
    assert result["value"] == 0
    assert result["candidates"][0]["acquisition_status"] == status
    expired = resolve([candidate(acquisition_status=status, valid_until=AT)])
    assert expired["fact_status"] == "stale"


@pytest.mark.parametrize(
    "state",
    [s.value for s in FactStatus if s not in {FactStatus.VALUE, FactStatus.CONFIRMED_ABSENT}],
)
def test_non_value_states_are_explained_not_zero(state):
    result = resolve([candidate(original_fact_status=state, fact_status=state, value=None)])
    assert result["fact_status"] == state
    assert result["value"] is None


@pytest.mark.parametrize("value", [None, True, "5", float("nan"), float("inf"), {}, 1e300])
def test_invalid_temperature_cannot_become_a_value(value):
    result = resolve([candidate(value=value)])
    assert result["fact_status"] == "unknown" and result["value"] is None
    assert result["candidates"][0]["reason"] == "invalid_field_value"


def test_unapproved_source_is_retained_but_never_selected():
    result = resolve([candidate("newsapi", 42), candidate(value=0)])
    assert result["value"] == 0 and result["selected_indexes"] == [1]
    assert result["candidates"][0]["reason"] == "source_not_admitted"


def test_all_admitted_sources_must_be_frozen_even_if_missing():
    with pytest.raises(ValueError, match="declared"):
        resolve(rule=policy(sources={"open_meteo": 1, "api_football": 10}))


def test_frozen_missing_and_failed_only_stream_remain_unknown():
    ref, _ = candidate()
    assert resolve([(ref, None)])["fact_status"] == "unknown"
    result = resolve(
        [
            (
                ref,
                candidate(
                    revision_id=None,
                    original_fact_status=None,
                    value=None,
                    last_success_acquired_at=None,
                    acquisition_status="failed",
                )[1],
            )
        ]
    )
    assert result["fact_status"] == "unknown"


@pytest.mark.parametrize("changes", [{"match_id": 2}, {"subject_key": "team:1"}])
def test_wrong_match_or_subject_does_not_fallback_to_other_stream(changes):
    with pytest.raises(ValueError, match="declared|subject"):
        resolve(**changes)


def test_reconstruction_is_not_a_runtime_resolution():
    with pytest.raises(ValueError, match="research"):
        resolve(cutoff=ObservationCutoff(CUTOFF.id, AT, True))


@pytest.mark.parametrize(
    "changes",
    [
        {"max_age_seconds": True},
        {"max_age_seconds": 0},
        {"max_age_seconds": 86401},
        {"sources": {}},
        {"sources": {"open_meteo": True}},
        {"sources": {"missing_source": 1}},
        {"version": ""},
        {"extractor": "pretend/v1"},
        {"field": "something.else"},
    ],
)
def test_invalid_trusted_policy_fails_closed(changes):
    with pytest.raises((ValueError, KeyError)):
        resolve(rule=policy(**changes))


def team_rule(domain):
    field = "lineup.starters" if domain == "lineup" else "injuries.complete_report"
    return policy(
        field=field,
        domain=domain,
        subject="team",
        extractor=field + "/v1",
        sources={"api_football": 10},
        max_age_seconds=1800,
    )


def team_resolve(domain, value, **obs_changes):
    ref, obs = candidate("api_football", **obs_changes)
    ref.update(domain=domain, subject_key="team:12")
    obs["value"] = value
    return resolve(
        [(ref, obs)], team_rule(domain), subject_key="team:12", field=team_rule(domain)["field"]
    )


def roster():
    return {
        "team_id": 12,
        "players": [{"player_id": i, "is_starting": True} for i in range(11, 0, -1)],
    }


def test_lineup_is_canonical_eleven_id_set_and_ignores_legacy_heuristics():
    value = roster()
    value["strength_score"] = 999
    result = team_resolve("lineup", value)
    assert result["value"] == list(range(1, 12))
    assert value["players"][0]["player_id"] == 11


@pytest.mark.parametrize(
    "change", ["partial", "duplicate", "wrong_team", "bool_id", "nonbool_start"]
)
def test_bad_roster_is_not_a_confirmed_lineup(change):
    value = roster()
    if change == "partial":
        value["players"].pop()
    if change == "duplicate":
        value["players"][0]["player_id"] = 1
    if change == "wrong_team":
        value["team_id"] = 13
    if change == "bool_id":
        value["players"][0]["player_id"] = True
    if change == "nonbool_start":
        value["players"][0]["is_starting"] = "false"
    assert team_resolve("lineup", value)["fact_status"] == "unknown"


@pytest.mark.parametrize(
    "state,value", [("value", {"team_id": 12, "players": []}), ("confirmed_absent", None)]
)
def test_empty_or_absent_injuries_without_coverage_are_unknown(state, value):
    result = team_resolve("injuries", value, original_fact_status=state, fact_status=state)
    assert result["fact_status"] == "unknown"
    assert result["candidates"][0]["reason"] == "coverage_unverified"


def test_covered_absence_is_none_not_zero_and_not_a_lineup_absence():
    args = dict(
        original_fact_status="confirmed_absent",
        fact_status="confirmed_absent",
        evidence={"coverage_complete": True, "coverage_evidence": "fixed-only/v1"},
    )
    assert team_resolve("injuries", None, **args)["fact_status"] == "confirmed_absent"
    assert team_resolve("lineup", None, **args)["fact_status"] == "unknown"


def test_complete_report_keeps_raw_reason_and_does_not_score_injuries():
    value = {
        "team_id": 12,
        "players": [
            {
                "player_id": 2,
                "source_player_id": 999,
                "reported_type": "Missing Fixture",
                "reported_reason": "knock",
                "impact_score": 0.9,
            }
        ],
    }
    result = team_resolve(
        "injuries",
        deepcopy(value),
        evidence={"coverage_complete": True, "coverage_evidence": "fixed-only/v1"},
    )
    assert result["value"] == [
        {"player_id": 2, "reported_type": "Missing Fixture", "reported_reason": "knock"}
    ]


def test_policy_hash_and_original_indices_are_deterministic():
    items = [candidate(), candidate("api_football", 5)]
    p = policy(sources={"api_football": 20, "open_meteo": 10})
    first = resolve(items, p)
    second = resolve(items, {**p, "sources": dict(reversed(list(p["sources"].items())))})
    assert first == second
