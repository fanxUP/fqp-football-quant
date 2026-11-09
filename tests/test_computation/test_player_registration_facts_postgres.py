"""P108-02 migration and eligibility regressions, isolated loopback PostgreSQL only."""

from __future__ import annotations

import os
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import errors, sql
from psycopg2.extensions import parse_dsn
from psycopg2.extras import Json

from scripts.player_identity_bridge import upsert_player_identity_link
from scripts.player_registration_facts import (
    RegistrationFactConflict,
    get_registration_eligibility,
    record_registration_fact,
)

ROOT = Path(__file__).resolve().parents[2]
HISTORY = ROOT / "sql/119_football_history_backfill.sql"
IDENTITY = ROOT / "sql/134_player_identity_bridge.sql"
UP = ROOT / "sql/135_player_affiliation_eligibility.sql"
DOWN = ROOT / "sql/down/135_player_affiliation_eligibility.down.sql"
NOW = datetime(2025, 8, 2, 10, tzinfo=UTC)


@pytest.fixture
def database():
    dsn = os.environ.get("FQP_PLAYER_REGISTRATION_TEST_DSN") or os.environ.get(
        "FQP_HISTORY_TEST_DSN", ""
    )
    if not dsn:
        pytest.skip("explicit isolated player-registration PostgreSQL database not supplied")
    params = parse_dsn(dsn)
    assert params.get("host") in {"127.0.0.1", "localhost"}
    dbname = params.get("dbname", "")
    assert dbname.startswith("fqp_player_registration_test_") or dbname == "fqp_history_test_ci"
    assert params.get("user") == "postgres"
    role_created = False
    with closing(psycopg2.connect(dsn)) as conn:
        schema = "player_registration_" + uuid4().hex
        with conn.cursor() as cur:
            if dbname.startswith("fqp_player_registration_test_"):
                cur.execute(
                    "SELECT shobj_description(oid,'pg_database') FROM pg_database "
                    "WHERE datname=current_database()"
                )
                assert cur.fetchone() == ("fqp-p108-player-registration-test/v1",)
            cur.execute(
                "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolcanlogin "
                "FROM pg_roles WHERE rolname='fqp'"
            )
            role = cur.fetchone()
            if role is None:
                cur.execute(
                    "CREATE ROLE fqp NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                )
                role_created = True
            else:
                assert role == (False, False, False, False, False, False)
            cur.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION CURRENT_USER").format(
                    sql.Identifier(schema)
                )
            )
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute(
                "CREATE TABLE players(id BIGINT PRIMARY KEY, player_code VARCHAR(64) UNIQUE)"
            )
            cur.execute("CREATE TABLE seasons(id BIGINT PRIMARY KEY)")
            cur.execute("CREATE TABLE competitions(id BIGINT PRIMARY KEY)")
            cur.execute(
                """CREATE TABLE competition_seasons(
                       id BIGINT PRIMARY KEY,
                       competition_id BIGINT NOT NULL REFERENCES competitions(id),
                       season_id BIGINT NOT NULL REFERENCES seasons(id),
                       UNIQUE(competition_id,season_id))"""
            )
            cur.execute("CREATE TABLE teams(id BIGINT PRIMARY KEY)")
            cur.execute("CREATE TABLE official_matches(id BIGINT PRIMARY KEY)")
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
            cur.execute("GRANT SELECT ON players TO fqp")
            cur.execute(HISTORY.read_text(encoding="utf-8"))
            cur.execute(IDENTITY.read_text(encoding="utf-8"))
            cur.execute(UP.read_text(encoding="utf-8"))
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("RESET ROLE")
                cur.execute("RESET search_path")
                cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
                if role_created:
                    cur.execute("DROP ROLE fqp")
            conn.commit()


def _rows(conn, query, params=()):
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def _create_competition_season(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO competitions(id) VALUES (9)")
        cur.execute("INSERT INTO seasons(id) VALUES (26)")
        cur.execute(
            "INSERT INTO competition_seasons(id,competition_id,season_id) VALUES (9001,9,26)"
        )
        cur.execute("INSERT INTO players(id,player_code) VALUES (701,'local:701')")
    conn.commit()


def _authority(
    conn,
    *,
    source_name="league_registry",
    status="approved",
    revision=1,
    reviewed_at=NOW,
    created_at=None,
):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO player_registration_authority_sources
               (source_name,revision,authority,status,source_reference,content_sha256,reviewed_by,reviewed_at,created_at)
               VALUES (%s,%s,'competition_registry',%s,%s,%s,'fixed-reviewer',%s,COALESCE(%s,clock_timestamp()))""",
            (
                source_name,
                revision,
                status,
                "https://league.example.invalid/registration-policy",
                "d" * 64,
                reviewed_at,
                created_at,
            ),
        )
    conn.commit()


def _fact(**changes):
    fact = {
        "source_name": "league_registry",
        "external_player_id": "42",
        "source_competition_id": "eng.1",
        "source_season": "2025-26",
        "competition_season_id": 9001,
        "source_record_key": "registration/42",
        "source_revision": "notice-v1",
        "content_sha256": "a" * 64,
        "status": "confirmed",
        "eligible": True,
        "source_authority": "competition_registry",
        "valid_from": date(2025, 8, 1),
        "valid_to": date(2026, 6, 1),
        "acquired_at": NOW,
        "source_published_at": datetime(2025, 8, 1, 8, tzinfo=UTC),
        "evidence_refs": ["https://league.example.invalid/registration/42"],
        "reviewed_by": "fixed-reviewer",
        "reviewed_at": NOW,
    }
    fact.update(changes)
    return fact


def _lookup(conn, *, valid_at=date(2025, 8, 2), known_at=NOW):
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


def _future_cutoff(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT clock_timestamp() + INTERVAL '1 hour'")
        return cur.fetchone()[0]


def test_published_titan_transfer_is_candidate_and_only_verified_identity_resolves(database):
    conn = database
    _create_competition_season(conn)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO football_history_batches
               (source_name,content_sha256,normalization_version,state,manifest)
               VALUES ('titan007',%s,'titan007-history/v1','building','{}') RETURNING id""",
            ("b" * 64,),
        )
        batch_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO football_history_records
               (batch_id,domain,source_record_key,source_player_id,origin,value_json)
               VALUES (%s,'player_transfers','transfer/42',42,'reported',%s)""",
            (
                batch_id,
                Json(
                    {
                        "effective_date": "2025-01-15",
                        "end_date_normalized": None,
                        "from_team_id": 101,
                        "from_name": "旧队",
                        "to_team_id": 202,
                        "to_name": "新队",
                    }
                ),
            ),
        )
        cur.execute(
            "UPDATE football_history_batches SET state='published' WHERE id=%s", (batch_id,)
        )
    conn.commit()

    candidate = upsert_player_identity_link(
        conn,
        source_name="titan007",
        external_player_id="42",
        player_id=701,
        status="candidate",
        evidence_refs=["history:transfer/42"],
        matching_method="manual_review",
        confidence=0.9,
    )
    row = _rows(
        conn,
        """SELECT canonical_player_id,identity_status,transfer_effective_date,
                  source_batch_sha256,normalization_version,affiliation_status,
                  current_affiliation_confirmed,registration_eligibility_confirmed
           FROM player_affiliation_candidates WHERE batch_id=%s""",
        (batch_id,),
    )[0]
    assert row == (
        None,
        "candidate",
        "2025-01-15",
        "b" * 64,
        "titan007-history/v1",
        "candidate_only",
        False,
        False,
    )
    assert candidate["status"] == "candidate"

    upsert_player_identity_link(
        conn,
        source_name="titan007",
        external_player_id="42",
        player_id=701,
        status="verified",
        evidence_refs=["history:transfer/42", "fixed:identity-review"],
        matching_method="manual_review",
        confidence=1,
        reviewed_by="fixed-reviewer",
        reviewed_at=NOW,
    )
    resolved = _rows(
        conn,
        "SELECT canonical_player_id FROM player_affiliation_candidates WHERE batch_id=%s",
        (batch_id,),
    )
    assert resolved == [(701,)]


def test_database_evidence_reference_constraint_rejects_duplicates_and_blanks(database):
    assert _rows(
        database,
        "SELECT player_registration_evidence_refs_valid('[\"row:1\"]'::jsonb)",
    ) == [(True,)]
    assert _rows(
        database,
        'SELECT player_registration_evidence_refs_valid(\'["row:1","row:1"]\'::jsonb)',
    ) == [(False,)]
    assert _rows(
        database,
        "SELECT player_registration_evidence_refs_valid('[\" \" ]'::jsonb)",
    ) == [(False,)]


def test_missing_and_future_acquired_facts_are_unknown_then_verified_fact_is_cutoff_safe(database):
    conn = database
    _create_competition_season(conn)
    _authority(conn)
    upsert_player_identity_link(
        conn,
        source_name="league_registry",
        external_player_id="42",
        player_id=701,
        status="candidate",
        evidence_refs=["registration:42"],
        matching_method="manual_review",
        confidence=0.9,
    )

    missing = _lookup(conn, known_at=datetime(2025, 8, 1, tzinfo=UTC))
    assert missing["status"] == "unknown"
    assert missing["reason"] == "no_fact_known_at_cutoff"
    assert missing["eligible"] is None

    created = record_registration_fact(conn, _fact())
    replay = record_registration_fact(conn, _fact())
    assert created["inserted"] is True
    assert replay["inserted"] is False
    assert replay["id"] == created["id"]
    with pytest.raises(RegistrationFactConflict, match="same source revision"):
        record_registration_fact(conn, _fact(eligible=False))
    conn.rollback()

    before_acquisition = _lookup(conn, known_at=datetime(2025, 8, 2, 9, tzinfo=UTC))
    assert before_acquisition["status"] == "unknown"
    after_acquisition = _lookup(conn, known_at=_future_cutoff(conn))
    assert after_acquisition["status"] == "confirmed"
    assert after_acquisition["eligible"] is True
    assert after_acquisition["canonical_player_id"] is None
    assert after_acquisition["canonical_player_resolved"] is False

    upsert_player_identity_link(
        conn,
        source_name="league_registry",
        external_player_id="42",
        player_id=701,
        status="verified",
        evidence_refs=["registration:42", "fixed:identity-review"],
        matching_method="manual_review",
        confidence=1,
        reviewed_by="fixed-reviewer",
        reviewed_at=NOW,
    )
    mapping_updated_at = _rows(
        conn,
        "SELECT updated_at FROM player_identity_links WHERE source_name='league_registry' AND external_player_id='42'",
    )[0][0]
    before_identity_review = _lookup(conn, known_at=mapping_updated_at - timedelta(microseconds=1))
    assert before_identity_review["status"] == "confirmed"
    assert before_identity_review["canonical_player_id"] is None
    assert before_identity_review["canonical_player_resolved"] is False

    at_mapping_update = _lookup(conn, known_at=mapping_updated_at)
    assert at_mapping_update["canonical_player_id"] == 701
    assert at_mapping_update["identity_mapping_updated_at"] == mapping_updated_at

    usable = _lookup(conn, known_at=_future_cutoff(conn))
    assert usable["canonical_player_id"] == 701
    assert usable["canonical_player_resolved"] is True


def test_backfilled_fact_is_not_visible_before_its_system_insertion_time(database):
    conn = database
    _create_competition_season(conn)
    _authority(conn)
    cutoff = _rows(conn, "SELECT clock_timestamp()")[0][0]

    record_registration_fact(conn, _fact())
    created_at = _rows(
        conn,
        "SELECT created_at FROM player_registration_facts WHERE source_record_key='registration/42'",
    )[0][0]
    assert created_at > cutoff

    before_backfill = _lookup(conn, known_at=cutoff)
    assert before_backfill["status"] == "unknown"
    assert before_backfill["reason"] == "no_fact_known_at_cutoff"

    at_backfill = _lookup(conn, known_at=created_at)
    assert at_backfill["status"] == "confirmed"
    after_backfill = _lookup(conn, known_at=created_at + timedelta(microseconds=1))
    assert after_backfill["status"] == "confirmed"


def test_fact_reviewed_after_cutoff_is_not_used_until_review_time(database):
    conn = database
    _create_competition_season(conn)
    _authority(conn)
    cutoff = _future_cutoff(conn)
    reviewed_at = cutoff + timedelta(hours=1)
    record_registration_fact(
        conn,
        _fact(
            acquired_at=cutoff - timedelta(hours=2),
            reviewed_at=reviewed_at,
        ),
    )

    before_review = _lookup(conn, known_at=cutoff)
    assert before_review["status"] == "unknown"
    assert before_review["reason"] == "no_fact_known_at_cutoff"

    at_review = _lookup(conn, known_at=reviewed_at)
    assert at_review["status"] == "confirmed"
    after_review = _lookup(conn, known_at=reviewed_at + timedelta(microseconds=1))
    assert after_review["status"] == "confirmed"


def test_identity_mapping_reviewed_after_cutoff_is_not_resolved(database):
    conn = database
    _create_competition_season(conn)
    _authority(conn)
    record_registration_fact(conn, _fact())
    cutoff = _future_cutoff(conn)
    reviewed_at = cutoff + timedelta(hours=1)
    upsert_player_identity_link(
        conn,
        source_name="league_registry",
        external_player_id="42",
        player_id=701,
        status="verified",
        evidence_refs=["registration:42", "future:identity-review"],
        matching_method="manual_review",
        confidence=1,
        reviewed_by="fixed-reviewer",
        reviewed_at=reviewed_at,
    )
    mapping_updated_at = _rows(
        conn,
        "SELECT updated_at FROM player_identity_links WHERE source_name='league_registry' AND external_player_id='42'",
    )[0][0]
    assert mapping_updated_at < cutoff < reviewed_at

    before_review = _lookup(conn, known_at=cutoff)
    assert before_review["status"] == "confirmed"
    assert before_review["canonical_player_id"] is None
    assert before_review["canonical_player_resolved"] is False

    at_review = _lookup(conn, known_at=reviewed_at)
    assert at_review["canonical_player_id"] == 701
    assert at_review["canonical_player_resolved"] is True
    after_review = _lookup(conn, known_at=reviewed_at + timedelta(microseconds=1))
    assert after_review["canonical_player_id"] == 701
    assert after_review["canonical_player_resolved"] is True


def test_authority_reviewed_after_cutoff_is_not_approved_at_that_cutoff(database):
    conn = database
    _create_competition_season(conn)
    cutoff = _future_cutoff(conn)
    reviewed_at = cutoff + timedelta(hours=1)
    _authority(conn, reviewed_at=reviewed_at)
    record_registration_fact(conn, _fact())

    before_review = _lookup(conn, known_at=cutoff)
    assert before_review["status"] == "unknown"
    assert before_review["reason"] == "authority_not_approved_at_cutoff"

    at_review = _lookup(conn, known_at=reviewed_at)
    assert at_review["status"] == "confirmed"
    after_review = _lookup(conn, known_at=reviewed_at + timedelta(microseconds=1))
    assert after_review["status"] == "confirmed"


def test_knowledge_cutoff_includes_acquisition_and_review_times_at_equality(database):
    conn = database
    _create_competition_season(conn)
    cutoff = _future_cutoff(conn)
    _authority(conn, reviewed_at=cutoff, created_at=cutoff)
    record_registration_fact(conn, _fact(acquired_at=cutoff, reviewed_at=cutoff))
    upsert_player_identity_link(
        conn,
        source_name="league_registry",
        external_player_id="42",
        player_id=701,
        status="verified",
        evidence_refs=["registration:42", "identity:exact-cutoff"],
        matching_method="manual_review",
        confidence=1,
        reviewed_by="fixed-reviewer",
        reviewed_at=cutoff,
    )

    at_cutoff = _lookup(conn, known_at=cutoff)
    assert at_cutoff["status"] == "confirmed"
    assert at_cutoff["canonical_player_id"] == 701
    assert at_cutoff["evidence"]["acquired_at"] == cutoff
    assert at_cutoff["evidence"]["reviewed_at"] == cutoff
    assert at_cutoff["authority"]["created_at"] == cutoff
    assert at_cutoff["authority"]["reviewed_at"] == cutoff
    assert at_cutoff["identity_mapping_reviewed_at"] == cutoff


def test_unknown_revision_supersedes_prior_true_and_valid_to_is_exclusive(database):
    conn = database
    _create_competition_season(conn)
    _authority(conn)
    record_registration_fact(conn, _fact())
    cutoff = _future_cutoff(conn)
    assert _lookup(conn, valid_at=date(2026, 5, 31), known_at=cutoff)["eligible"] is True
    assert (
        _lookup(conn, valid_at=date(2026, 6, 1), known_at=cutoff)["reason"]
        == "outside_validity_interval"
    )

    record_registration_fact(
        conn,
        _fact(
            source_revision="notice-v2",
            content_sha256="c" * 64,
            status="unknown",
            eligible=None,
            source_authority="unknown",
            valid_from=None,
            valid_to=None,
            acquired_at=datetime(2025, 8, 3, tzinfo=UTC),
            source_published_at=None,
            reviewed_by=None,
            reviewed_at=None,
            evidence_refs=["https://league.example.invalid/notice-v2"],
        ),
    )
    latest = _lookup(conn, known_at=_future_cutoff(conn))
    assert latest["status"] == "unknown"
    assert latest["eligible"] is None
    assert latest["reason"] == "source_reports_unknown"


def test_unregistered_authority_cannot_publish_confirmed_fact(database):
    conn = database
    _create_competition_season(conn)
    with pytest.raises(errors.RaiseException, match="active reviewed authority source"):
        record_registration_fact(conn, _fact())
    conn.rollback()
    assert _rows(conn, "SELECT count(*) FROM player_registration_facts") == [(0,)]


def test_authority_must_be_explicitly_approved_and_revisions_are_sequential(database):
    conn = database
    _create_competition_season(conn)
    _authority(conn)
    with pytest.raises(errors.RaiseException, match="revisions must increase by one"):
        _authority(conn, status="suspended", revision=3)
    conn.rollback()
    _authority(conn, status="suspended", revision=2)

    with pytest.raises(errors.RaiseException, match="active reviewed authority source"):
        record_registration_fact(conn, _fact())
    conn.rollback()
    assert _rows(conn, "SELECT status FROM player_registration_authority_current") == [
        ("suspended",)
    ]
    assert _rows(conn, "SELECT count(*) FROM player_registration_facts") == [(0,)]


def test_current_eligibility_projection_fails_closed_after_authority_suspension(database):
    conn = database
    _create_competition_season(conn)
    _authority(conn)
    current_day = _rows(conn, "SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date")[0][0]
    record_registration_fact(
        conn,
        _fact(
            valid_from=current_day - timedelta(days=1),
            valid_to=current_day + timedelta(days=1),
        ),
    )
    assert _rows(
        conn,
        "SELECT fact_status,status,eligible,authority_status FROM player_registration_eligibility_current",
    ) == [("confirmed", "confirmed", True, "approved")]

    _authority(conn, status="suspended", revision=2)
    assert _rows(
        conn,
        "SELECT fact_status,status,eligible,authority_status FROM player_registration_eligibility_current",
    ) == [("confirmed", "unknown", None, "suspended")]


def test_current_eligibility_projection_does_not_claim_an_expired_fact(database):
    conn = database
    _create_competition_season(conn)
    _authority(conn)
    current_day = _rows(conn, "SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date")[0][0]
    record_registration_fact(
        conn,
        _fact(valid_from=current_day - timedelta(days=10), valid_to=current_day),
    )

    assert _rows(
        conn,
        "SELECT fact_status,status,eligible FROM player_registration_eligibility_current",
    ) == [("confirmed", "unknown", None)]


def test_current_eligibility_projection_ignores_future_revision_without_masking_current(database):
    conn = database
    _create_competition_season(conn)
    _authority(conn)
    current_day = _rows(conn, "SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date")[0][0]
    current = record_registration_fact(
        conn,
        _fact(
            valid_from=current_day - timedelta(days=1),
            valid_to=current_day + timedelta(days=1),
        ),
    )
    future_acquired_at = _rows(conn, "SELECT clock_timestamp() + INTERVAL '1 hour'")[0][0]
    record_registration_fact(
        conn,
        _fact(
            source_revision="notice-v2",
            content_sha256="c" * 64,
            acquired_at=future_acquired_at,
            reviewed_at=future_acquired_at + timedelta(hours=1),
            valid_from=current_day - timedelta(days=1),
            valid_to=current_day + timedelta(days=1),
        ),
    )

    assert _rows(
        conn,
        "SELECT fact_id,source_revision,status,eligible FROM player_registration_eligibility_current",
    ) == [(current["id"], "notice-v1", "confirmed", True)]


def test_current_eligibility_projection_hides_future_reviewed_authority(database):
    conn = database
    _create_competition_season(conn)
    reviewed_at = _rows(conn, "SELECT clock_timestamp() + INTERVAL '1 hour'")[0][0]
    _authority(conn, reviewed_at=reviewed_at)
    current_day = _rows(conn, "SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date")[0][0]
    record_registration_fact(
        conn,
        _fact(
            valid_from=current_day - timedelta(days=1),
            valid_to=current_day + timedelta(days=1),
        ),
    )

    assert _rows(
        conn,
        "SELECT fact_status,status,eligible,authority_status FROM player_registration_eligibility_current",
    ) == [("confirmed", "unknown", None, "approved")]


def test_current_eligibility_projection_hides_future_reviewed_identity_mapping(database):
    conn = database
    _create_competition_season(conn)
    _authority(conn)
    current_day = _rows(conn, "SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date")[0][0]
    record_registration_fact(
        conn,
        _fact(
            valid_from=current_day - timedelta(days=1),
            valid_to=current_day + timedelta(days=1),
        ),
    )
    reviewed_at = _rows(conn, "SELECT clock_timestamp() + INTERVAL '1 hour'")[0][0]
    upsert_player_identity_link(
        conn,
        source_name="league_registry",
        external_player_id="42",
        player_id=701,
        status="verified",
        evidence_refs=["registration:42", "future:identity-review"],
        matching_method="manual_review",
        confidence=1,
        reviewed_by="fixed-reviewer",
        reviewed_at=reviewed_at,
    )

    assert _rows(
        conn,
        "SELECT canonical_player_id,status FROM player_registration_eligibility_current",
    ) == [(None, "confirmed")]


def test_eligibility_lookup_uses_authority_state_known_at_the_cutoff(database):
    conn = database
    _create_competition_season(conn)
    approval_reviewed_at = _future_cutoff(conn) + timedelta(hours=1)
    _authority(conn, reviewed_at=approval_reviewed_at)
    record_registration_fact(conn, _fact())
    approved_at = _rows(
        conn,
        "SELECT created_at FROM player_registration_authority_sources WHERE source_name='league_registry' AND revision=1",
    )[0][0]

    suspension_reviewed_at = approval_reviewed_at + timedelta(hours=1)
    _authority(
        conn,
        status="suspended",
        revision=2,
        reviewed_at=suspension_reviewed_at,
    )
    suspended_at = _rows(
        conn,
        "SELECT created_at FROM player_registration_authority_sources WHERE source_name='league_registry' AND revision=2",
    )[0][0]
    before_approval = _lookup(conn, known_at=approval_reviewed_at - timedelta(microseconds=1))
    at_approved_cutoff = _lookup(conn, known_at=approval_reviewed_at + timedelta(microseconds=1))
    after_suspension = _lookup(conn, known_at=suspension_reviewed_at + timedelta(seconds=1))

    assert before_approval["status"] == "unknown"
    assert before_approval["reason"] == "authority_not_approved_at_cutoff"
    assert at_approved_cutoff["status"] == "confirmed"
    assert after_suspension["status"] == "unknown"
    assert after_suspension["reason"] == "authority_not_approved_at_cutoff"
    assert approved_at < approval_reviewed_at
    assert suspended_at < suspension_reviewed_at


def test_runtime_role_is_read_only_and_both_ledgers_are_append_only(database):
    conn = database
    _create_competition_season(conn)
    _authority(conn)
    record_registration_fact(conn, _fact())

    with conn.cursor() as cur:
        cur.execute("SET ROLE fqp")
        assert cur.execute("SELECT count(*) FROM player_registration_facts") is None
        cur.execute("SELECT count(*) FROM player_registration_authority_current")
        assert cur.fetchone() == (1,)
        denied = (
            "INSERT INTO player_registration_facts(source_name,external_player_id,source_competition_id,source_season,source_record_key,source_revision,content_sha256,status,eligible,source_authority,acquired_at,evidence_refs) VALUES ('x','1','c','s','r','v','"
            + "e" * 64
            + "','unknown',NULL,'unknown',now(),'[\"ref\"]')",
            "UPDATE player_registration_facts SET status='unknown'",
            "DELETE FROM player_registration_facts",
            "TRUNCATE player_registration_facts",
            "INSERT INTO player_registration_authority_sources(source_name,revision,authority,status,source_reference,content_sha256,reviewed_by,reviewed_at) VALUES ('x',1,'competition_registry','approved','ref','"
            + "f" * 64
            + "','reviewer',now())",
            "UPDATE player_registration_authority_sources SET status='suspended'",
            "DELETE FROM player_registration_authority_sources",
            "TRUNCATE player_registration_authority_sources",
        )
        for statement in denied:
            cur.execute("SET ROLE fqp")
            with pytest.raises(errors.InsufficientPrivilege):
                cur.execute(statement)
            conn.rollback()

    for statement in (
        "UPDATE player_registration_facts SET status='unknown'",
        "DELETE FROM player_registration_facts",
        "TRUNCATE player_registration_facts",
        "UPDATE player_registration_authority_sources SET status='suspended'",
        "DELETE FROM player_registration_authority_sources",
        "TRUNCATE player_registration_authority_sources",
    ):
        with pytest.raises(errors.RaiseException, match="append-only"):
            with conn.cursor() as cur:
                cur.execute(statement)
        conn.rollback()


def test_migration_up_down_up_and_down_refuses_to_drop_source_evidence(database):
    conn = database
    assert _rows(conn, "SELECT count(*) FROM player_registration_authority_sources") == [(0,)]
    assert _rows(conn, "SELECT count(*) FROM player_registration_facts") == [(0,)]
    with conn.cursor() as cur:
        cur.execute(DOWN.read_text(encoding="utf-8"))
        cur.execute(UP.read_text(encoding="utf-8"))
    conn.commit()
    assert _rows(conn, "SELECT count(*) FROM player_registration_facts") == [(0,)]

    _create_competition_season(conn)
    _authority(conn)
    record_registration_fact(conn, _fact())
    with pytest.raises(errors.RaiseException, match="preserve reviewed evidence"):
        with conn.cursor() as cur:
            cur.execute(DOWN.read_text(encoding="utf-8"))
    conn.rollback()
    assert _rows(conn, "SELECT count(*) FROM player_registration_facts") == [(1,)]
    assert _rows(conn, "SELECT count(*) FROM player_registration_authority_sources") == [(1,)]
