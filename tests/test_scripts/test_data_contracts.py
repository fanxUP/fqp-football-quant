from datetime import UTC, datetime

import pytest

from scripts.data_contracts import (
    AcquisitionStatus,
    EntityKind,
    ExternalIdentity,
    FactStatus,
    IdentityResolution,
    ResolutionStatus,
    to_utc,
)


@pytest.mark.parametrize(
    ("candidates", "status", "resolved_id"),
    [
        ((), ResolutionStatus.UNRESOLVED, None),
        ((11,), ResolutionStatus.RESOLVED, 11),
        ((11, 12), ResolutionStatus.AMBIGUOUS, None),
    ],
)
def test_resolution_never_selects_first_ambiguous_candidate(candidates, status, resolved_id):
    result = IdentityResolution(EntityKind.TEAM, "sporttery", "测试队", candidates)
    assert result.status == status
    assert result.resolved_id == resolved_id
    assert result.mapping_revision is None  # no invented database mapping revision


@pytest.mark.parametrize("candidate", [0, -1, True, "11"])
def test_resolution_rejects_invalid_internal_ids(candidate):
    with pytest.raises(ValueError):
        IdentityResolution(EntityKind.TEAM, "sporttery", "测试队", (candidate,))


def test_external_ids_are_scoped_by_entity_and_source():
    team = ExternalIdentity(EntityKind.TEAM, "api_football", "11")
    player = ExternalIdentity(EntityKind.PLAYER, "api_football", "11")
    official = ExternalIdentity(EntityKind.TEAM, "sporttery", "11")
    assert len({team, player, official}) == 3
    assert team.key == ("team", "api_football", "11")


@pytest.mark.parametrize(
    "namespace,external_id", [("", "11"), ("Bad/source", "11"), ("sporttery", " ")]
)
def test_external_identity_rejects_empty_or_unscoped_keys(namespace, external_id):
    with pytest.raises(ValueError):
        ExternalIdentity(EntityKind.TEAM, namespace, external_id)


def test_naive_timestamp_requires_explicit_producer_timezone():
    with pytest.raises(ValueError, match="timezone"):
        to_utc(datetime(2026, 10, 16, 1))


def test_existing_naive_business_time_is_not_assumed_utc():
    assert to_utc(datetime(2026, 10, 16, 1), naive_timezone="Asia/Shanghai") == datetime(
        2026, 10, 15, 17, tzinfo=UTC
    )


def test_aware_timestamp_retains_its_actual_offset():
    value = datetime.fromisoformat("2026-10-16T01:00:00+08:00")
    assert to_utc(value) == datetime(2026, 10, 15, 17, tzinfo=UTC)


@pytest.mark.parametrize("value", [datetime(2026, 3, 8, 2, 30), datetime(2026, 11, 1, 1, 30)])
def test_dst_gap_or_overlap_requires_explicit_aware_timestamp(value):
    with pytest.raises(ValueError, match="aware"):
        to_utc(value, naive_timezone="America/New_York")


def test_fact_status_and_acquisition_status_are_separate_vocabulary():
    assert FactStatus.UNKNOWN.value != FactStatus.CONFIRMED_ABSENT.value
    assert FactStatus.NOT_PUBLISHED.value != FactStatus.NOT_COVERED.value
    assert AcquisitionStatus.SUCCESS.value == "success"
    assert AcquisitionStatus.QUOTA_EXHAUSTED.value == "quota_exhausted"
