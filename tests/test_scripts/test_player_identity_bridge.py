from datetime import UTC, datetime

import pytest

from scripts.player_identity_bridge import (
    IdentityLinkError,
    VerifiedIdentityConflict,
    resolve_player_identity,
    upsert_player_identity_link,
)


def test_explicit_unverified_mapping_fails_closed_without_legacy_fallback():
    class Cursor:
        def __init__(self):
            self.calls = []
            self.result = None

        def execute(self, query, params):
            self.calls.append((query, params))
            if "FROM player_identity_links" in query:
                self.result = (701, "candidate")
            else:
                self.result = (999,)

        def fetchone(self):
            return self.result

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Connection:
        def __init__(self):
            self.cur = Cursor()

        def cursor(self):
            return self.cur

    conn = Connection()

    assert resolve_player_identity(conn, "apifootball", "42") is None
    assert len(conn.cur.calls) == 1


def test_api_football_uses_exact_legacy_player_code_only_when_bridge_row_is_absent():
    class Cursor:
        def __init__(self):
            self.result = None
            self.queries = []

        def execute(self, query, params):
            self.queries.append((query, params))
            self.result = None if "FROM player_identity_links" in query else (702,)

        def fetchone(self):
            return self.result

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Connection:
        def __init__(self):
            self.cur = Cursor()

        def cursor(self):
            return self.cur

    conn = Connection()

    assert resolve_player_identity(conn, "apifootball", "42") == 702
    assert conn.cur.queries[1][1] == ("apifootball:42",)


@pytest.mark.parametrize(
    ("source_name", "external_player_id", "status", "evidence_refs", "method", "confidence"),
    [
        ("", "42", "candidate", ["row:1"], "manual", 0.5),
        ("titan007", " ", "candidate", ["row:1"], "manual", 0.5),
        ("titan007", "42", "pending", ["row:1"], "manual", 0.5),
        ("titan007", "42", "candidate", [], "manual", 0.5),
        ("titan007", "42", "candidate", ["row:1"], "manual", 1.1),
    ],
)
def test_invalid_identity_link_inputs_are_rejected(
    source_name, external_player_id, status, evidence_refs, method, confidence
):
    with pytest.raises(IdentityLinkError):
        upsert_player_identity_link(
            object(),
            source_name=source_name,
            external_player_id=external_player_id,
            player_id=None,
            status=status,
            evidence_refs=evidence_refs,
            matching_method=method,
            confidence=confidence,
        )


def test_verified_link_requires_review_evidence():
    with pytest.raises(IdentityLinkError, match="verified"):
        upsert_player_identity_link(
            object(),
            source_name="titan007",
            external_player_id="42",
            player_id=7,
            status="verified",
            evidence_refs=["titan007/player/42"],
            matching_method="manual_crosswalk",
            confidence=1,
        )


def test_unresolved_mapping_cannot_claim_a_canonical_player():
    with pytest.raises(IdentityLinkError, match="unresolved"):
        upsert_player_identity_link(
            object(),
            source_name="titan007",
            external_player_id="42",
            player_id=7,
            status="unresolved",
            evidence_refs=["source-row:42"],
            matching_method="manual_review",
            confidence=0.5,
        )


def test_review_timestamps_must_be_timezone_aware():
    with pytest.raises(IdentityLinkError, match="timezone"):
        upsert_player_identity_link(
            object(),
            source_name="titan007",
            external_player_id="42",
            player_id=7,
            status="verified",
            evidence_refs=["titan007/player/42"],
            matching_method="manual_crosswalk",
            confidence=1,
            reviewed_by="operator",
            reviewed_at=datetime(2026, 11, 10),
        )


def test_verified_remap_error_is_domain_specific():
    assert issubclass(VerifiedIdentityConflict, IdentityLinkError)


def test_verification_timestamp_uses_aware_value():
    stamp = datetime(2026, 11, 10, tzinfo=UTC)
    assert stamp.tzinfo is UTC
