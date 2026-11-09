from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest

from scripts.data_catalog import get_data_product, load_data_catalog
from scripts.player_registration_facts import (
    RegistrationFactError,
    get_registration_eligibility,
    validate_registration_fact,
)


def fact(**changes):
    value = {
        "source_name": "league_registry",
        "external_player_id": " 42 ",
        "source_competition_id": "eng.1",
        "source_season": "2025-26",
        "competition_season_id": 9001,
        "source_record_key": "registration/42",
        "source_revision": "notice-v1",
        "content_sha256": "a" * 64,
        "status": "confirmed",
        "eligible": True,
        "source_authority": "competition_registry",
        "valid_from": "2025-08-01",
        "valid_to": "2026-06-01",
        "acquired_at": datetime(2025, 8, 2, 9, tzinfo=UTC),
        "source_published_at": datetime(2025, 8, 1, 12, tzinfo=UTC),
        "evidence_refs": ["https://league.example.invalid/registration/42"],
        "reviewed_by": "fixed-reviewer",
        "reviewed_at": datetime(2025, 8, 2, 10, tzinfo=UTC),
    }
    value.update(changes)
    return value


def test_confirmed_fact_normalizes_identity_and_effective_dates():
    normalized = validate_registration_fact(fact())

    assert normalized["source_name"] == "league_registry"
    assert normalized["external_player_id"] == "42"
    assert normalized["valid_from"] == date(2025, 8, 1)
    assert normalized["valid_to"] == date(2026, 6, 1)
    assert normalized["status"] == "confirmed"
    assert normalized["eligible"] is True


@pytest.mark.parametrize(
    "changes",
    [
        {"eligible": None},
        {"competition_season_id": None},
        {"valid_from": None},
        {"valid_to": None},
        {"source_authority": "unknown"},
        {"reviewed_by": None, "reviewed_at": None},
        {"evidence_refs": []},
        {"reviewed_at": datetime(2025, 8, 1, tzinfo=UTC)},
        {"status": []},
        {"source_authority": []},
    ],
)
def test_confirmed_fact_requires_authority_time_and_review_evidence(changes):
    with pytest.raises(RegistrationFactError):
        validate_registration_fact(fact(**changes))


def test_unknown_fact_cannot_carry_an_eligibility_boolean():
    with pytest.raises(RegistrationFactError, match="unknown facts cannot assert eligibility"):
        validate_registration_fact(fact(status="unknown", eligible=False))


def test_naive_acquisition_time_is_rejected():
    with pytest.raises(RegistrationFactError, match="timezone-aware"):
        validate_registration_fact(fact(acquired_at=datetime(2025, 8, 2, 9)))


def _lookup(conn, row, *, valid_at, known_at):
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = row
    with (
        patch(
            "scripts.player_registration_facts._canonical_player_at_cutoff",
            return_value=(701, known_at, known_at),
        ),
        patch(
            "scripts.player_registration_facts._authority_at_cutoff",
            return_value={
                "authority": "competition_registry",
                "status": "approved",
                "revision": 1,
                "created_at": known_at,
                "reviewed_at": known_at,
            },
        ),
    ):
        return get_registration_eligibility(
            conn,
            source_name="league_registry",
            external_player_id="42",
            source_competition_id="eng.1",
            source_season="2025-26",
            competition_season_id=9001,
            valid_at=valid_at,
            known_at=known_at,
        )


def test_missing_fact_fails_closed_to_unknown_at_requested_knowledge_time():
    conn = MagicMock()
    known_at = datetime(2025, 8, 1, tzinfo=UTC)

    result = _lookup(conn, None, valid_at=date(2025, 8, 2), known_at=known_at)

    assert result["status"] == "unknown"
    assert result["eligible"] is None
    assert result["reason"] == "no_fact_known_at_cutoff"
    assert result["canonical_player_resolved"] is False
    cursor = conn.cursor.return_value.__enter__.return_value
    assert "acquired_at <= %s" in cursor.execute.call_args.args[0]
    assert "created_at <= %s" in cursor.execute.call_args.args[0]
    assert "reviewed_at <= %s" in cursor.execute.call_args.args[0]
    assert cursor.execute.call_args.args[1][-3:] == (known_at, known_at, known_at)


def test_confirmed_fact_is_unknown_when_outside_effective_interval():
    acquired_at = datetime(2025, 8, 2, tzinfo=UTC)
    row = (
        51,
        "confirmed",
        True,
        "competition_registry",
        date(2025, 8, 1),
        date(2026, 6, 1),
        acquired_at,
        acquired_at,
        datetime(2025, 8, 1, tzinfo=UTC),
        "registration/42",
        "notice-v1",
        "a" * 64,
        ["https://league.example.invalid/registration/42"],
        "fixed-reviewer",
        acquired_at,
    )

    result = _lookup(
        MagicMock(),
        row,
        valid_at=date(2026, 6, 1),
        known_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    assert result["status"] == "unknown"
    assert result["eligible"] is None
    assert result["reason"] == "outside_validity_interval"
    assert result["fact_id"] == 51


def test_catalog_keeps_transfer_candidates_separate_from_registration_truth():
    catalog = load_data_catalog()
    affiliation = get_data_product("player_affiliation_candidates", purpose="research")
    eligibility = get_data_product("player_registration_eligibility", purpose="research")

    assert catalog["runtime_authorization"] is False
    assert catalog["sources"]["titan007"]["storage_role"] == "raw_source_cache_not_business_truth"
    assert "candidate" in affiliation["availability"]
    assert "verified_identity" in affiliation["availability"]
    assert "missing_or_out_of_scope_facts_return_unknown" in eligibility["availability"]
    assert "prediction" not in catalog["products"]["player_registration_eligibility"]["purposes"]
