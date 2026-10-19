"""Opt-in frozen field decisions against the owned P104 fixture database."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from scripts.data_catalog import get_data_source, get_field_resolution_policy
from scripts.data_contracts import AcquisitionStatus, FactStatus
from scripts.observation_resolution import resolve_observed_field
from scripts.observation_storage import (
    append_observation,
    capture_observation_cutoff,
    load_observation_as_of,
    load_observation_cutoff,
    record_acquisition_failure,
)
from tests.test_computation import test_observation_postgres as obs
from tests.test_computation import test_player_observations_postgres as player_fixtures

connect = obs.connect
pg = obs.pg
match_id = obs.match_id
match = player_fixtures.match


def stream(mid, source="open_meteo"):
    return dict(match_id=mid, source_id=source, domain="weather", subject_key="forecast")


def write(pg, mid, value=0, source="open_meteo", **changes):
    at = datetime.now(UTC) - timedelta(seconds=1)
    args = dict(
        **stream(mid, source),
        fact_status=FactStatus.VALUE,
        value={"temperature_2m": value},
        acquired_at=at,
        verified_at=at,
        effective_at=datetime(2026, 11, 1, tzinfo=UTC),
        valid_until=at + timedelta(hours=6),
    )
    args.update(changes)
    result = append_observation(pg, **args)
    pg.commit()
    return result


def freeze(pg, mid, sources=("open_meteo",)):
    cutoff = capture_observation_cutoff(pg, streams=[stream(mid, s) for s in sources])
    pg.commit()
    return cutoff


def resolve(pg, mid, cutoff, **changes):
    return resolve_observed_field(
        pg,
        cutoff=cutoff,
        match_id=mid,
        subject_key="forecast",
        field="weather.temperature_2m",
        **changes,
    )


def test_real_cutoff_resolves_future_forecast_zero_without_writes(pg, match_id):
    write(pg, match_id)
    cutoff = freeze(pg, match_id)
    pg.rollback()
    with pg.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SET LOCAL ROLE fqp_observation_reader")
    result = resolve(pg, match_id, cutoff)
    assert result["value"] == 0 and result["fact_status"] == "value"
    assert result["candidates"][0]["last_success_acquired_at"] is not None
    pg.rollback()


def test_correction_and_failure_do_not_change_old_decision(pg, match_id):
    first = write(pg, match_id)
    cutoff = freeze(pg, match_id)
    before = resolve(pg, match_id, cutoff)
    second = write(pg, match_id, 20)
    assert first["revision_id"] != second["revision_id"]
    record_acquisition_failure(
        pg,
        **stream(match_id),
        status=AcquisitionStatus.QUOTA_EXHAUSTED,
        acquired_at=datetime.now(UTC),
    )
    pg.commit()
    later = freeze(pg, match_id)
    assert resolve(pg, match_id, cutoff) == before
    current = resolve(pg, match_id, later)
    assert current["value"] == 20
    assert current["candidates"][0]["acquisition_status"] == "quota_exhausted"


def test_same_content_refresh_resets_freshness_but_not_revision(pg, match_id):
    past = datetime.now(UTC) - timedelta(hours=8)
    first = write(pg, match_id, acquired_at=past, verified_at=past, valid_until=None)
    old = freeze(pg, match_id)
    assert resolve(pg, match_id, old)["fact_status"] == "stale"
    second = write(pg, match_id, valid_until=None)
    assert first["revision_id"] == second["revision_id"]
    new = freeze(pg, match_id)
    assert resolve(pg, match_id, new)["value"] == 0
    assert resolve(pg, match_id, old)["fact_status"] == "stale"


@pytest.mark.parametrize(
    "first_value,second_value,expected", [(0, 0, "value"), (0, 10, "conflict")]
)
def test_equal_priority_real_competing_evidence_is_not_averaged(
    pg, match_id, first_value, second_value, expected
):
    write(pg, match_id, first_value)
    write(pg, match_id, second_value, source="api_football")
    cutoff = freeze(pg, match_id, ("open_meteo", "api_football"))
    p = get_field_resolution_policy("weather.temperature_2m")
    p["sources"]["api_football"] = 10  # Isolated synthetic policy, never a real provider grant.
    result = resolve(pg, match_id, cutoff, policy=p)
    assert result["fact_status"] == expected
    assert len(result["candidates"]) == 2
    assert result["value"] == (0 if expected == "value" else None)


def test_cutoff_pins_missing_source_despite_later_backfill(pg, match_id):
    cutoff = freeze(pg, match_id)
    write(pg, match_id)
    assert resolve(pg, match_id, cutoff)["fact_status"] == "unknown"
    assert resolve(pg, match_id, freeze(pg, match_id))["value"] == 0


def renamed_source(source):
    value = get_data_source(source)
    return dict(value, family="renamed_feed")


def test_frozen_family_is_readable_after_catalog_family_changes(pg, match_id):
    write(pg, match_id)
    cutoff = freeze(pg, match_id)
    before = resolve(pg, match_id, cutoff)
    with patch("scripts.observation_storage.get_data_source", side_effect=renamed_source):
        restored = load_observation_cutoff(pg, cutoff.id)
        assert load_observation_as_of(pg, **stream(match_id), cutoff=restored)["value"] == {
            "temperature_2m": 0
        }
        assert resolve(pg, match_id, restored) == before


def test_new_capture_rejects_family_drift_instead_of_faking_missing(pg, match_id):
    write(pg, match_id)
    with patch("scripts.observation_storage.get_data_source", side_effect=renamed_source):
        with pytest.raises(ValueError, match="family"):
            freeze(pg, match_id)
    pg.rollback()


def test_new_append_still_rejects_family_drift(pg, match_id):
    write(pg, match_id)
    with patch("scripts.observation_storage.get_data_source", side_effect=renamed_source):
        with pytest.raises(ValueError, match="family"):
            write(pg, match_id, 10)
    pg.rollback()


def test_historical_policy_snapshot_replays_after_default_changes(pg, match_id):
    write(pg, match_id)
    cutoff = freeze(pg, match_id)
    before = resolve(pg, match_id, cutoff)
    changed = deepcopy(before["policy"])
    changed["max_age_seconds"] = 1
    changed["version"] = "observation-fields/v2"
    with patch("scripts.observation_resolution.get_field_resolution_policy", return_value=changed):
        assert resolve(pg, match_id, cutoff)["policy_hash"] != before["policy_hash"]
        assert resolve(pg, match_id, cutoff, policy=before["policy"]) == before


def test_read_error_does_not_fallback_to_latest(pg, match_id):
    write(pg, match_id)
    cutoff = freeze(pg, match_id)
    with pg.cursor() as cur:
        cur.execute("ALTER TABLE observation_cutoffs DISABLE TRIGGER observation_immutable")
        cur.execute(
            "UPDATE observation_cutoffs SET content_hash=%s WHERE id=%s", ("0" * 64, cutoff.id)
        )
    try:
        with pytest.raises(ValueError, match="hash"):
            resolve(pg, match_id, cutoff)
    finally:
        pg.rollback()


def test_actual_lineup_adapter_resolves_canonical_roster_and_keeps_old_cutoff(pg, match):
    player_fixtures.save_lineup(pg, match)
    cutoff = player_fixtures.freeze(pg, match)
    args = dict(
        match_id=match["id"], subject_key=f"team:{match['home_team_id']}", field="lineup.starters"
    )
    original = resolve_observed_field(pg, cutoff=cutoff, **args)
    assert original["fact_status"] == "value" and len(original["value"]) == 11
    player_fixtures.save_lineup(pg, match, player_fixtures.lineup(2))
    assert resolve_observed_field(pg, cutoff=cutoff, **args) == original
    new = resolve_observed_field(pg, cutoff=player_fixtures.freeze(pg, match), **args)
    assert original["value"] != new["value"]


@pytest.mark.parametrize(
    "covered,rows,state",
    [
        (False, False, "unknown"),
        (False, True, "unknown"),
        (True, False, "confirmed_absent"),
        (True, True, "value"),
    ],
)
def test_actual_injury_adapter_requires_coverage_for_complete_report(
    pg, match, covered, rows, state
):
    player_fixtures.save_injuries(
        pg,
        match,
        [player_fixtures.injury(880)] if rows else [],
        coverage_evidence="isolated-fixed/v1" if covered else None,
    )
    cutoff = player_fixtures.freeze(pg, match)
    result = resolve_observed_field(
        pg,
        cutoff=cutoff,
        match_id=match["id"],
        subject_key=f"team:{match['home_team_id']}",
        field="injuries.complete_report",
    )
    assert result["fact_status"] == state
    if state == "value":
        assert set(result["value"][0]) == {"player_id", "reported_type", "reported_reason"}
    else:
        assert result["value"] is None
