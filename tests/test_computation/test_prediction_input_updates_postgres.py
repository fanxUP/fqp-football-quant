"""Explicit isolated PG16 fixtures; no production, providers or cache services."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import psycopg2
import pytest

from scripts.data_contracts import AcquisitionStatus
from scripts.observation_storage import record_acquisition_failure
from scripts.prediction_input_updates import (
    InputUpdateLeaseLost,
    InputUpdateSuperseded,
    claim_input_updates,
    complete_input_update,
    release_input_update,
)
from tests.test_computation import test_observation_postgres as obs

connect = obs.connect
pg = obs.pg
match_id = obs.match_id


def query(conn, sql, args=()):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall() if cur.description else None


@pytest.fixture
def consumer_factory(pg):
    # Preserve append-only fixture history. A new configured consumer begins
    # after older tests' heads, before this test appends its own observations.
    def create():
        key = "fixture/" + uuid4().hex
        query(
            pg,
            "INSERT INTO prediction_input_consumers(consumer_key,match_id,completed_version) "
            "SELECT %s,match_id,input_version FROM prediction_input_dirty_matches",
            (key,),
        )
        pg.commit()
        return key

    return create


@pytest.fixture
def consumer(consumer_factory):
    return consumer_factory()


def seed(pg, mid):
    ref = obs.write(pg, mid)
    pg.commit()
    return ref


def take(pg, key):
    claims = claim_input_updates(pg, consumer_key=key)
    pg.commit()
    assert len(claims) == 1
    return claims[0]


def head(pg, mid):
    rows = query(
        pg,
        "SELECT input_version,last_check_id FROM prediction_input_dirty_matches WHERE match_id=%s",
        (mid,),
    )
    return rows[0] if rows else None


def expire(pg, claim):
    # Controlled clock fault, without sleeping or changing the server clock.
    query(
        pg,
        "UPDATE prediction_input_consumers SET lease_until=clock_timestamp()-interval '1 second' "
        "WHERE consumer_key=%s AND match_id=%s",
        (claim.consumer_key, claim.match_id),
    )
    pg.commit()


def publication_table(pg):
    query(pg, "CREATE TEMP TABLE fixture_publications(version bigint)")
    pg.commit()


def publish(pg, claim):
    query(pg, "INSERT INTO fixture_publications VALUES (%s)", (claim.input_version,))
    return {"fixture_version": claim.input_version}


def test_fact_and_notification_commit_and_rollback_together(pg, connect, match_id, consumer):
    first = obs.write(pg, match_id)
    assert head(pg, match_id) == (1, first["check_id"])
    with closing(connect()) as other:
        assert head(other, match_id) is None
        assert claim_input_updates(other, consumer_key=consumer) == []
        other.rollback()
    pg.rollback()
    assert head(pg, match_id) is None
    assert query(pg, "SELECT id FROM observation_streams WHERE match_id=%s", (match_id,)) == []
    pg.rollback()
    second = seed(pg, match_id)
    assert head(pg, match_id) == (1, second["check_id"])
    obs.write(pg, match_id, value=999)
    pg.rollback()
    assert head(pg, match_id) == (1, second["check_id"])
    assert take(pg, consumer).input_version == 1


@pytest.mark.parametrize("kind", ["source_observation", "candidate", "research_reconstruction"])
def test_same_content_refresh_notifies_without_new_revision(pg, match_id, kind):
    first = obs.write(pg, match_id, evidence_kind=kind)
    pg.commit()
    second = obs.write(pg, match_id, evidence_kind=kind)
    pg.commit()
    assert first["revision_id"] == second["revision_id"]
    assert head(pg, match_id) == (2, second["check_id"])


@pytest.mark.parametrize("status", [s for s in AcquisitionStatus if s != AcquisitionStatus.SUCCESS])
def test_failure_quota_and_recovery_each_notify(pg, match_id, status):
    first = seed(pg, match_id)
    check = record_acquisition_failure(
        pg,
        match_id=match_id,
        source_id="open_meteo",
        domain="weather",
        subject_key="forecast",
        status=status,
        acquired_at=datetime.now(UTC),
    )
    pg.commit()
    assert head(pg, match_id) == (2, check)
    recovered = seed(pg, match_id)
    assert recovered["revision_id"] == first["revision_id"]
    assert head(pg, match_id) == (3, recovered["check_id"])


def test_notification_failure_rolls_back_fact_write(pg, match_id):
    seed(pg, match_id)
    before = head(pg, match_id)
    # Overflow the bounded counter in a rolled-back fault transaction.
    query(pg, "SAVEPOINT fixture_fault")
    query(
        pg,
        "UPDATE prediction_input_dirty_matches SET input_version=9223372036854775807 "
        "WHERE match_id=%s",
        (match_id,),
    )
    with pytest.raises(psycopg2.errors.NumericValueOutOfRange):
        obs.write(pg, match_id, value=999)
    query(pg, "ROLLBACK TO SAVEPOINT fixture_fault")
    assert head(pg, match_id) == before
    assert query(
        pg,
        "SELECT count(*) FROM observation_revisions r JOIN observation_streams s "
        "ON s.id=r.stream_id WHERE s.match_id=%s",
        (match_id,),
    ) == [(1,)]


def test_concurrent_source_receipts_have_no_lost_increment(pg, connect, match_id):
    barrier = Barrier(4)

    def append(_):
        with closing(connect()) as conn:
            barrier.wait(timeout=5)
            ref = obs.write(conn, match_id)
            conn.commit()
            return ref

    with ThreadPoolExecutor(max_workers=4) as pool:
        refs = list(pool.map(append, range(4)))
    assert head(pg, match_id)[0] == 4
    assert len({r["revision_id"] for r in refs}) == 1
    assert len({r["check_id"] for r in refs}) == 4


def test_concurrent_claims_are_disjoint_and_bounded(pg, connect, match_id, consumer):
    mids = [match_id] + [obs.match_id.__wrapped__(pg) for _ in range(6)]
    for mid in mids:
        seed(pg, mid)
    barrier = Barrier(4)

    def claim(_):
        with closing(connect()) as conn:
            barrier.wait(timeout=5)
            rows = claim_input_updates(conn, consumer_key=consumer, limit=2)
            conn.commit()
            assert len(rows) <= 2
            return rows

    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(claim, range(4)))
    claimed = [c.match_id for batch in batches for c in batch]
    assert len(claimed) == len(set(claimed))
    # A worker can skip rows held by another transaction; a later pass fills gaps.
    claimed += [c.match_id for c in claim_input_updates(pg, consumer_key=consumer)]
    assert set(claimed) == set(mids)
    assert len(claimed) == 7


def test_held_head_is_skipped_and_uncommitted_claim_rolls_back(pg, connect, match_id, consumer):
    seed(pg, match_id)
    with closing(connect()) as other:
        claim = claim_input_updates(pg, consumer_key=consumer)[0]
        assert claim_input_updates(other, consumer_key=consumer) == []
        other.rollback()
        pg.rollback()
        replacement = claim_input_updates(other, consumer_key=consumer)[0]
        other.commit()
        assert replacement.token != claim.token
        assert replacement.attempt_count == 1


def test_consumers_have_independent_completion(pg, match_id, consumer, consumer_factory):
    second = consumer_factory()
    seed(pg, match_id)
    first_claim = take(pg, consumer)
    second_claim = take(pg, second)
    complete_input_update(pg, first_claim, lambda *_: {"first": True})
    pg.commit()
    assert claim_input_updates(pg, consumer_key=consumer) == []
    assert (
        complete_input_update(pg, second_claim, lambda *_: {"second": True})["status"]
        == "completed"
    )


def test_expired_claim_is_reclaimed_and_old_token_is_fenced(pg, match_id, consumer):
    seed(pg, match_id)
    old = take(pg, consumer)
    assert claim_input_updates(pg, consumer_key=consumer) == []
    pg.rollback()
    expire(pg, old)
    new = take(pg, consumer)
    assert new.token != old.token and new.attempt_count == 2
    assert release_input_update(pg, old) is False
    with pytest.raises(InputUpdateLeaseLost):
        complete_input_update(pg, old, lambda *_: pytest.fail("old worker published"))
    assert complete_input_update(pg, new, lambda *_: {"new": True})["status"] == "completed"


def test_expired_without_replacement_cannot_complete(pg, match_id, consumer):
    seed(pg, match_id)
    claim = take(pg, consumer)
    expire(pg, claim)
    with pytest.raises(InputUpdateLeaseLost):
        complete_input_update(pg, claim, lambda *_: pytest.fail("expired worker published"))


def test_release_retains_pending_and_only_own_token(pg, match_id, consumer):
    seed(pg, match_id)
    claim = take(pg, consumer)
    assert release_input_update(pg, replace(claim, token=str(uuid4()))) is False
    assert release_input_update(pg, claim) is True
    pg.commit()
    new = take(pg, consumer)
    assert new.input_version == claim.input_version and new.attempt_count == 2


def test_update_during_computation_cannot_publish_or_clear_new_version(
    pg, connect, match_id, consumer
):
    seed(pg, match_id)
    old = take(pg, consumer)
    with closing(connect()) as other:
        seed(other, match_id)
    with pytest.raises(InputUpdateSuperseded):
        complete_input_update(pg, old, lambda *_: pytest.fail("superseded worker published"))
    assert release_input_update(pg, old)
    pg.commit()
    new = take(pg, consumer)
    assert new.input_version == 2
    assert complete_input_update(pg, new, lambda *_: {"current": 2})["status"] == "completed"
    pg.commit()
    assert claim_input_updates(pg, consumer_key=consumer) == []


def test_publication_receipt_and_position_atomic_and_duplicate_safe(pg, match_id, consumer):
    publication_table(pg)
    seed(pg, match_id)
    claim = take(pg, consumer)
    result = complete_input_update(pg, claim, publish)
    pg.commit()
    assert result == {
        "status": "completed",
        "input_version": 1,
        "result_refs": {"fixture_version": 1},
    }
    seed(pg, match_id)  # An old receipt replay must not invoke a new callback.
    assert complete_input_update(pg, claim, lambda *_: pytest.fail("duplicate publication")) == {
        **result,
        "status": "already_completed",
    }
    assert query(pg, "SELECT * FROM fixture_publications") == [(1,)]
    assert take(pg, consumer).input_version == 2


def test_outer_rollback_removes_publication_receipt_and_completion(pg, match_id, consumer):
    publication_table(pg)
    seed(pg, match_id)
    claim = take(pg, consumer)
    complete_input_update(pg, claim, publish)
    pg.rollback()
    assert query(pg, "SELECT * FROM fixture_publications") == []
    assert query(
        pg,
        "SELECT completed_version,lease_token::text FROM prediction_input_consumers "
        "WHERE consumer_key=%s AND match_id=%s",
        (consumer, match_id),
    ) == [(0, claim.token)]
    assert (
        query(pg, "SELECT * FROM prediction_input_consumptions WHERE consumer_key=%s", (consumer,))
        == []
    )
    assert complete_input_update(pg, claim, publish)["status"] == "completed"


@pytest.mark.parametrize("fault", ["exception", "sql_error", "not_object", "nan", "oversized"])
def test_callback_failure_cannot_leave_partial_writes_even_if_caller_commits(
    pg, match_id, consumer, fault
):
    publication_table(pg)
    seed(pg, match_id)
    claim = take(pg, consumer)

    def broken(conn, current):
        publish(conn, current)
        if fault == "exception":
            raise RuntimeError("synthetic failure")
        if fault == "sql_error":
            query(conn, "SELECT 1/0")
        return {"not_object": [], "nan": {"x": float("nan")}, "oversized": {"x": "界" * 16384}}[
            fault
        ]

    with pytest.raises((RuntimeError, ValueError, psycopg2.errors.DivisionByZero)):
        complete_input_update(pg, claim, broken)
    pg.commit()
    assert query(pg, "SELECT * FROM fixture_publications") == []
    assert (
        query(pg, "SELECT * FROM prediction_input_consumptions WHERE consumer_key=%s", (consumer,))
        == []
    )
    assert complete_input_update(pg, claim, publish)["status"] == "completed"


@pytest.mark.parametrize("fault", ["expire", "input_change"])
def test_post_callback_fence_rolls_back_all_callback_writes(pg, match_id, consumer, fault):
    publication_table(pg)
    seed(pg, match_id)
    claim = take(pg, consumer)

    def broken(conn, current):
        refs = publish(conn, current)
        if fault == "expire":
            query(
                conn,
                "UPDATE prediction_input_consumers SET lease_until=clock_timestamp()-interval '1 second' "
                "WHERE consumer_key=%s AND match_id=%s",
                (consumer, match_id),
            )
        else:
            obs.write(conn, match_id, value=999)  # Deliberate internal contract violation.
        return refs

    with pytest.raises(InputUpdateLeaseLost if fault == "expire" else InputUpdateSuperseded):
        complete_input_update(pg, claim, broken)
    pg.commit()
    assert query(pg, "SELECT * FROM fixture_publications") == []
    assert head(pg, match_id)[0] == 1
    assert complete_input_update(pg, claim, publish)["status"] == "completed"


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_consumption_history_rejects_mutation(pg, match_id, consumer, operation):
    seed(pg, match_id)
    complete_input_update(pg, take(pg, consumer), lambda *_: {})
    pg.commit()
    sql = {
        "UPDATE": "UPDATE prediction_input_consumptions SET result_refs='{}'",
        "DELETE": "DELETE FROM prediction_input_consumptions",
        "TRUNCATE": "TRUNCATE prediction_input_consumptions",
    }[operation]
    with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState, match="append-only"):
        query(pg, sql)
    pg.rollback()


@pytest.mark.parametrize(
    "changes",
    [
        {"match_id": True},
        {"input_version": 0},
        {"attempt_count": -1},
        {"token": "invalid"},
        {"lease_until": datetime(2026, 1, 1)},
    ],
)
def test_claim_identity_validation(pg, match_id, consumer, changes):
    seed(pg, match_id)
    claim = take(pg, consumer)
    with pytest.raises(ValueError):
        replace(claim, **changes)


@pytest.mark.parametrize(
    "options",
    [
        {"consumer_key": "User key"},
        {"consumer_key": "x" * 65},
        {"limit": True},
        {"limit": 33},
        {"lease_seconds": 9},
        {"lease_seconds": 901},
    ],
)
def test_claim_arguments_reject_unbounded_or_implicit_values(pg, options):
    with pytest.raises(ValueError):
        claim_input_updates(pg, **{"consumer_key": "fixture/validation", **options})


def test_all_mutation_helpers_reject_autocommit(pg, match_id, consumer):
    seed(pg, match_id)
    claim = take(pg, consumer)
    pg.autocommit = True
    try:
        for run in (
            lambda: claim_input_updates(pg, consumer_key=consumer),
            lambda: release_input_update(pg, claim),
            lambda: complete_input_update(pg, claim, lambda *_: {}),
        ):
            with pytest.raises(ValueError, match="caller-owned transaction"):
                run()
    finally:
        pg.autocommit = False


def test_writer_notifies_without_queue_update_permission_and_reader_cannot_write(pg, match_id):
    query(pg, "SET ROLE fqp_observation_writer")
    ref = obs.write(pg, match_id)
    pg.commit()
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        query(pg, "UPDATE prediction_input_dirty_matches SET input_version=input_version+1")
    pg.rollback()
    query(pg, "RESET ROLE")
    query(pg, "SET ROLE fqp_observation_reader")
    assert head(pg, match_id) == (1, ref["check_id"])
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        claim_input_updates(pg, consumer_key="fixture/forbidden")
    pg.rollback()
    query(pg, "RESET ROLE")


def test_consumer_can_lock_claim_complete_but_not_mutate_facts_or_receipts(pg, match_id, consumer):
    seed(pg, match_id)
    query(pg, "SET ROLE fqp_input_consumer")
    claim = take(pg, consumer)
    assert complete_input_update(pg, claim, lambda *_: {"fixture": True})["status"] == "completed"
    pg.commit()
    for sql in (
        "UPDATE observation_checks SET acquired_at=clock_timestamp()",
        "DELETE FROM prediction_input_consumptions",
    ):
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            query(pg, sql)
        pg.rollback()
    query(pg, "RESET ROLE")


def test_trigger_security_and_queue_constraints_are_validated(pg):
    row = query(
        pg,
        "SELECT prosecdef,proconfig,has_function_privilege('fqp_observation_writer',"
        "'notify_prediction_input_update()','EXECUTE') FROM pg_proc "
        "WHERE oid='notify_prediction_input_update()'::regprocedure",
    )[0]
    assert row == (True, ["search_path=pg_catalog"], False)
    rows = query(
        pg,
        "SELECT convalidated FROM pg_constraint WHERE conrelid=ANY(ARRAY["
        "'prediction_input_dirty_matches'::regclass,'prediction_input_consumers'::regclass,"
        "'prediction_input_consumptions'::regclass])",
    )
    assert len(rows) >= 12 and all(r[0] for r in rows)


def test_simultaneous_duplicate_completion_invokes_callback_once(pg, connect, match_id, consumer):
    seed(pg, match_id)
    claim = take(pg, consumer)
    barrier = Barrier(2)
    calls = []

    def finish(_):
        with closing(connect()) as conn:
            barrier.wait(timeout=5)

            def once(*_):
                calls.append(claim.token)
                return {"same_result": True}

            result = complete_input_update(conn, claim, once)
            conn.commit()
            return result["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(finish, range(2)))
    assert sorted(statuses) == ["already_completed", "completed"]
    assert calls == [claim.token]


def test_update_serializes_after_short_publication_transaction(pg, connect, match_id, consumer):
    seed(pg, match_id)
    claim = take(pg, consumer)
    complete_input_update(pg, claim, lambda *_: {"version": 1})
    with closing(connect()) as other:
        # Publication owns the input-head row lock until caller commits. A
        # competing fact write must fail/roll back, never disappear silently.
        with pytest.raises(psycopg2.errors.LockNotAvailable):
            obs.write(other, match_id, value={"new": True})
        other.rollback()
        pg.commit()
        seed(other, match_id)
    assert head(pg, match_id)[0] == 2
    assert take(pg, consumer).input_version == 2


@pytest.mark.parametrize("bad", ["claim", "callback"])
def test_completion_requires_explicit_claim_and_callback(pg, match_id, consumer, bad):
    seed(pg, match_id)
    claim = take(pg, consumer)
    with pytest.raises(ValueError):
        complete_input_update(
            pg, object() if bad == "claim" else claim, None if bad == "callback" else lambda *_: {}
        )


def test_claim_without_persisted_progress_cannot_publish(pg, match_id, consumer):
    seed(pg, match_id)
    claim = claim_input_updates(pg, consumer_key=consumer)[0]
    pg.rollback()
    with pytest.raises(InputUpdateLeaseLost):
        complete_input_update(pg, claim, lambda *_: pytest.fail("missing claim published"))
