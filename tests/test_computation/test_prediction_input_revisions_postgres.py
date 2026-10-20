"""Persisted P105 pilot: synthetic fixtures, explicit isolated PostgreSQL only."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import psycopg2
import pytest

from scripts.observed_feature_pipeline import build_observed_feature_batch
from scripts.prediction_input_revisions import (
    claim_prediction_input_revisions,
    complete_prediction_input_revision,
    load_prediction_input_revision,
)
from scripts.prediction_input_updates import InputUpdateSuperseded, release_input_update
from tests.test_computation import test_observed_pipeline_postgres as pipeline
from tests.test_computation import test_prediction_input_updates_postgres as updates
from tests.test_storage.test_prediction_input_policy import profile

connect = pipeline.connect
pg = pipeline.pg
match_id = pipeline.match_id
match = pipeline.match
consumer_factory = updates.consumer_factory
consumer = updates.consumer
query = updates.query


@pytest.fixture
def ready(pg, match, consumer):
    at = datetime.now(UTC)
    kickoff = at + timedelta(hours=3)
    names = [uuid4().hex, uuid4().hex]
    query(
        pg,
        "UPDATE official_matches SET home_team_name=%s,away_team_name=%s,kickoff_time=%s,"
        "sale_stop_time=%s,sale_status='selling' WHERE id=%s",
        (
            *names,
            kickoff.replace(tzinfo=None) + timedelta(hours=8),
            (at + timedelta(hours=2)).replace(tzinfo=None) + timedelta(hours=8),
            match["id"],
        ),
    )
    for name, side in zip(names, ("home", "away"), strict=True):
        query(
            pg,
            "INSERT INTO team_aliases(team_id,source_name,alias_name) VALUES (%s,'sporttery',%s)",
            (match[side + "_team_id"], name),
        )
    market = query(
        pg,
        "INSERT INTO official_markets(match_id,play_type,is_open) VALUES (%s,'spf',true) RETURNING id",
        (match["id"],),
    )[0][0]
    for option, value in [("h", 2), ("d", 3.5), ("a", 4)]:
        query(
            pg,
            "INSERT INTO official_odds_snapshots(match_id,market_id,play_type,option_code,option_name,sp_value,snapshot_time) "
            "VALUES (%s,%s,'spf',%s,%s,%s,%s)",
            (
                match["id"],
                market,
                option,
                option,
                value,
                at.replace(tzinfo=None) + timedelta(hours=8),
            ),
        )
    pg.commit()
    # Weather's target must match the canonical official kickoff.
    pipeline.weather(pg, match, effective_at=kickoff)
    claim = updates.take(pg, consumer)
    cutoff = pipeline.freeze(pg, match)
    batch = build_observed_feature_batch(
        pg,
        match_id=match["id"],
        cutoff=cutoff,
        context=dict(
            home_team_id=match["home_team_id"],
            away_team_id=match["away_team_id"],
            kickoff_at=kickoff.isoformat(),
        ),
    )
    pg.commit()
    return dict(
        claim=claim,
        batch_id=batch,
        cutoff=cutoff,
        market=market,
        kickoff=kickoff,
        profiles=(profile(),),
    )


def complete(pg, ready, **changes):
    args = dict(batch_id=ready["batch_id"], play_type="spf", profiles=ready["profiles"])
    args.update(changes)
    result = complete_prediction_input_revision(pg, ready["claim"], **args)
    pg.commit()
    return result["result_refs"]["input_revision_id"]


def read(pg, identifier):
    return load_prediction_input_revision(pg, identifier)


def test_persist_exact_batch_cutoff_and_duplicate_no_republication(pg, ready):
    identifier = complete(pg, ready)
    first = read(pg, identifier)
    assert first["status"] == "current" and first["recommendation_eligible"]
    assert first["decision"]["mode"] == "basic"
    assert first["feature_batch_id"] == ready["batch_id"]
    assert first["observation_cutoff_id"] == ready["cutoff"].id
    assert complete(pg, ready) == identifier
    assert query(
        pg, "SELECT count(*) FROM prediction_input_revisions WHERE id=%s", (identifier,)
    ) == [(1,)]


def test_outer_rollback_removes_revision_receipt_and_position(pg, ready):
    result = complete_prediction_input_revision(
        pg, ready["claim"], batch_id=ready["batch_id"], play_type="spf", profiles=ready["profiles"]
    )
    identifier = result["result_refs"]["input_revision_id"]
    pg.rollback()
    assert read(pg, identifier) is None
    assert complete(pg, ready) != identifier


def test_new_fact_invalidates_without_cache_and_preserves_history(pg, ready, match):
    identifier = complete(pg, ready)
    old = read(pg, identifier)["decision"]
    pipeline.weather(pg, match, 25, effective_at=ready["kickoff"])
    current = read(pg, identifier)
    assert (
        not current["recommendation_eligible"]
        and "input_version_changed" in current["invalidation_reasons"]
    )
    assert current["decision"] == old


@pytest.mark.parametrize(
    "change",
    [
        "sale_status='closed'",
        "sale_stop_time=timezone('Asia/Shanghai',clock_timestamp())",
        "kickoff_time=timezone('Asia/Shanghai',clock_timestamp())",
        "match_status='cancelled'",
        "source_match_id=source_match_id || '-changed'",
    ],
)
def test_official_changes_invalidate_atomically(pg, ready, match, change):
    identifier = complete(pg, ready)
    query(pg, "UPDATE official_matches SET " + change + " WHERE id=%s", (match["id"],))
    assert "input_version_changed" in read(pg, identifier)["invalidation_reasons"]
    pg.rollback()
    assert read(pg, identifier)["recommendation_eligible"]
    pg.rollback()
    query(pg, "UPDATE official_matches SET " + change + " WHERE id=%s", (match["id"],))
    pg.commit()
    assert not read(pg, identifier)["recommendation_eligible"]


@pytest.mark.parametrize("table", ["official_markets", "official_odds_snapshots"])
def test_market_changes_invalidate_and_rollback_together(pg, ready, match, table):
    identifier = complete(pg, ready)
    query(pg, "UPDATE " + table + " SET is_open=false WHERE match_id=%s", (match["id"],))
    assert not read(pg, identifier)["recommendation_eligible"]
    pg.rollback()
    assert read(pg, identifier)["recommendation_eligible"]


def test_missing_alias_only_restricts_this_revision(pg, ready, match):
    identifier = complete(pg, ready)
    query(pg, "DELETE FROM team_aliases WHERE team_id=%s", (match["home_team_id"],))
    pg.commit()
    assert "official_context_changed" in read(pg, identifier)["invalidation_reasons"]


def test_delayed_publication_after_sale_is_research_and_reopen_never_revives(pg, ready, match):
    # Clock is injected only into internal current-context reader, never a public API clock override.
    from scripts import prediction_input_revisions as revisions

    original = revisions._current

    def late(*args):
        state = original(*args)
        return (ready["kickoff"] + timedelta(seconds=1), *state[1:])

    with patch.object(revisions, "_current", side_effect=late):
        identifier = complete(pg, ready)
    result = read(pg, identifier)
    assert result["research_only"] and not result["recommendation_eligible"]


def test_old_cutoff_cannot_acknowledge_new_input_version(pg, ready, match):
    pipeline.weather(pg, match, 21, effective_at=ready["kickoff"])
    with pytest.raises(InputUpdateSuperseded):
        complete(pg, ready)
    pg.rollback()


def test_natural_expiry_current_read_checks_database_clock(pg, ready):
    identifier = complete(pg, ready, max_age_seconds=1)
    from scripts import prediction_input_revisions as revisions

    original = revisions._current
    with patch.object(
        revisions,
        "_current",
        side_effect=lambda *a: (datetime.now(UTC) + timedelta(seconds=10), *original(*a)[1:]),
    ):
        result = read(pg, identifier)
    assert (
        "input_expired" in result["invalidation_reasons"] and not result["recommendation_eligible"]
    )


@pytest.mark.parametrize(
    "operation",
    [
        "UPDATE prediction_input_revisions SET research_only=false",
        "DELETE FROM prediction_input_revisions",
        "TRUNCATE prediction_input_revisions",
    ],
)
def test_append_only_revisions(pg, ready, operation):
    complete(pg, ready)
    with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
        query(pg, operation)
    pg.rollback()


def test_market_fallback_retains_non_independent_identity(pg, ready):
    identifier = complete(pg, ready, profiles=())
    result = read(pg, identifier)
    assert result["decision"]["mode"] == "market_reference"
    assert not result["decision"]["model_independent"] and not result["recommendation_eligible"]


def test_shadow_profile_remains_research(pg, ready):
    identifier = complete(pg, ready, profiles=(replace(profile(), rollout_mode="shadow"),))
    assert read(pg, identifier)["research_only"]


@pytest.mark.parametrize("limit", [0, 33, True])
def test_claim_requires_bounded_limit(pg, limit):
    with pytest.raises(ValueError):
        claim_prediction_input_revisions(pg, consumer_key="pilot/v1", limit=limit)


@pytest.mark.parametrize("age", [0, 301, True])
def test_publication_rejects_invalid_age(pg, ready, age):
    with pytest.raises(ValueError):
        complete(pg, ready, max_age_seconds=age)


def rebuild(pg, ready, match):
    cutoff = pipeline.freeze(pg, match)
    batch = build_observed_feature_batch(
        pg,
        match_id=match["id"],
        cutoff=cutoff,
        context=dict(
            home_team_id=match["home_team_id"],
            away_team_id=match["away_team_id"],
            kickoff_at=ready["kickoff"].isoformat(),
        ),
    )
    pg.commit()
    return dict(ready, cutoff=cutoff, batch_id=batch)


def test_expired_head_refreshes_once_and_can_publish_new_revision(pg, ready, match):
    identifier = complete(pg, ready, max_age_seconds=1)
    query(pg, "SELECT pg_sleep(1.05)")
    assert "input_expired" in read(pg, identifier)["invalidation_reasons"]
    claims = claim_prediction_input_revisions(pg, consumer_key=ready["claim"].consumer_key, limit=1)
    pg.commit()
    assert len(claims) == 1 and claims[0].input_version == ready["claim"].input_version + 1
    assert (
        claim_prediction_input_revisions(pg, consumer_key=ready["claim"].consumer_key, limit=1)
        == []
    )
    pg.commit()
    ready = rebuild(pg, dict(ready, claim=claims[0]), match)
    newer = complete(pg, ready)
    assert newer != identifier and read(pg, newer)["recommendation_eligible"]
    assert "input_version_changed" in read(pg, identifier)["invalidation_reasons"]


def test_old_cutoff_after_reclaim_is_rejected(pg, ready, match):
    pipeline.weather(pg, match, 21, effective_at=ready["kickoff"])
    assert release_input_update(pg, ready["claim"])
    pg.commit()
    ready["claim"] = updates.take(pg, ready["claim"].consumer_key)
    with pytest.raises(InputUpdateSuperseded, match="cutoff predates"):
        complete(pg, ready)
    pg.rollback()
    ready = rebuild(pg, ready, match)
    assert read(pg, complete(pg, ready))["recommendation_eligible"]


def test_consumer_role_can_publish_and_read_but_cannot_mutate_revisions(pg, ready):
    query(pg, "SET ROLE fqp_input_consumer")
    identifier = complete(pg, ready)
    assert read(pg, identifier)["recommendation_eligible"]
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        query(pg, "DELETE FROM prediction_input_revisions WHERE id=%s", (identifier,))
    pg.rollback()


def test_observation_reader_cannot_publish(pg, ready):
    query(pg, "SET ROLE fqp_observation_reader")
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        complete(pg, ready)
    pg.rollback()


def test_official_write_waits_for_publication_fence_then_invalidates(pg, ready, match, connect):
    result = complete_prediction_input_revision(
        pg, ready["claim"], batch_id=ready["batch_id"], play_type="spf", profiles=ready["profiles"]
    )
    identifier = result["result_refs"]["input_revision_id"]

    def compete():
        with closing(connect()) as other:
            with pytest.raises(psycopg2.errors.LockNotAvailable):
                query(
                    other,
                    "UPDATE official_matches SET sale_status='closed' WHERE id=%s",
                    (match["id"],),
                )
            other.rollback()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(compete).result(timeout=5)
    pg.commit()
    query(pg, "UPDATE official_matches SET sale_status='closed' WHERE id=%s", (match["id"],))
    pg.commit()
    assert "input_version_changed" in read(pg, identifier)["invalidation_reasons"]


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_current_read_rejects_stale_transaction_snapshot(pg, ready, isolation):
    identifier = complete(pg, ready)
    pg.rollback()
    query(pg, "SET TRANSACTION ISOLATION LEVEL " + isolation)
    with pytest.raises(ValueError, match="READ COMMITTED"):
        read(pg, identifier)
    pg.rollback()


@pytest.mark.parametrize(
    "change", ["sale_stop_time=NULL", "sale_status='closed'", "match_status='cancelled'"]
)
def test_closed_state_persists_only_research(pg, ready, match, change):
    query(pg, "UPDATE official_matches SET " + change + " WHERE id=%s", (match["id"],))
    pg.commit()
    assert release_input_update(pg, ready["claim"])
    pg.commit()
    ready["claim"] = updates.take(pg, ready["claim"].consumer_key)
    ready = rebuild(pg, ready, match)
    result = read(pg, complete(pg, ready))
    assert result["research_only"] and not result["recommendation_eligible"]


def test_context_mismatch_never_authorizes_independent_input(pg, ready, match):
    query(
        pg,
        "UPDATE team_aliases SET team_id=%s WHERE team_id=%s",
        (match["away_team_id"], match["home_team_id"]),
    )
    pg.commit()
    result = read(pg, complete(pg, ready))
    assert "batch_official_context_mismatch" in result["invalidation_reasons"]
    assert not result["recommendation_eligible"]


def test_future_odds_without_new_write_expire_at_boundary(pg, ready, match):
    future = datetime.now(UTC) + timedelta(seconds=1)
    query(
        pg,
        "INSERT INTO official_odds_snapshots(match_id,market_id,play_type,option_code,option_name,sp_value,snapshot_time) VALUES (%s,%s,'spf','h','h',2.1,%s)",
        (match["id"], ready["market"], future.replace(tzinfo=None) + timedelta(hours=8)),
    )
    pg.commit()
    assert release_input_update(pg, ready["claim"])
    pg.commit()
    ready["claim"] = updates.take(pg, ready["claim"].consumer_key)
    ready = rebuild(pg, ready, match)
    identifier = complete(pg, ready)
    assert datetime.fromisoformat(read(pg, identifier)["valid_until"]) <= future
    query(pg, "SELECT pg_sleep(1.05)")
    assert "input_expired" in read(pg, identifier)["invalidation_reasons"]


def test_bound_sp_market_must_be_coherent(pg, ready, match):
    query(
        pg,
        "UPDATE official_odds_snapshots SET snapshot_time=snapshot_time-interval '1 minute' WHERE match_id=%s AND option_code='h'",
        (match["id"],),
    )
    pg.commit()
    assert release_input_update(pg, ready["claim"])
    pg.commit()
    ready["claim"] = updates.take(pg, ready["claim"].consumer_key)
    ready = rebuild(pg, ready, match)
    result = read(pg, complete(pg, ready))
    assert "invalid_official_market" in result["invalidation_reasons"]


@pytest.mark.parametrize("identifier", [0, True, -1, "1"])
def test_invalid_revision_identity(pg, identifier):
    with pytest.raises(ValueError):
        read(pg, identifier)


def test_absent_revision(pg):
    assert read(pg, 9223372036854775807) is None


def test_pilot_wrappers_use_persisted_current_gate(pg, ready):
    from scripts import prematch_feature_dataset as consumer

    result = consumer.complete_prediction_input_revision(
        pg, ready["claim"], batch_id=ready["batch_id"], play_type="spf", profiles=ready["profiles"]
    )
    pg.commit()
    assert consumer.load_prediction_input_revision(pg, result["result_refs"]["input_revision_id"])[
        "recommendation_eligible"
    ]


def test_refresh_rollback_restores_expired_version_and_reclaim(pg, ready):
    identifier = complete(pg, ready, max_age_seconds=1)
    query(pg, "SELECT pg_sleep(1.05)")
    first = claim_prediction_input_revisions(pg, consumer_key=ready["claim"].consumer_key, limit=1)[
        0
    ]
    pg.rollback()
    second = claim_prediction_input_revisions(
        pg, consumer_key=ready["claim"].consumer_key, limit=1
    )[0]
    pg.commit()
    assert first.input_version == second.input_version and first.token != second.token
    assert not read(pg, identifier)["recommendation_eligible"]


def test_concurrent_expiry_reclaim_does_not_double_bump(pg, ready, connect):
    complete(pg, ready, max_age_seconds=1)
    query(pg, "SELECT pg_sleep(1.05)")
    pg.commit()

    def take():
        with closing(connect()) as other:
            claims = claim_prediction_input_revisions(
                other, consumer_key=ready["claim"].consumer_key, limit=1
            )
            other.commit()
            return claims

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: take(), range(2)))
    claims = [claim for batch in results for claim in batch]
    assert len(claims) == 1 and claims[0].input_version == ready["claim"].input_version + 1


def test_future_source_availability_without_insert_expires_decision(pg, ready, match):
    future = datetime.now(UTC) + timedelta(seconds=1)
    pipeline.weather(pg, match, 9, effective_at=ready["kickoff"], published_at=future)
    assert release_input_update(pg, ready["claim"])
    pg.commit()
    ready["claim"] = updates.take(pg, ready["claim"].consumer_key)
    ready = rebuild(pg, ready, match)
    identifier = complete(pg, ready, profiles=())
    assert datetime.fromisoformat(read(pg, identifier)["valid_until"]) <= future
    query(pg, "SELECT pg_sleep(1.05)")
    assert "input_expired" in read(pg, identifier)["invalidation_reasons"]


@pytest.mark.parametrize("expired", [False, True])
def test_optional_source_failure_respects_retained_freshness(pg, ready, match, expired):
    from scripts.data_contracts import AcquisitionStatus
    from scripts.observation_storage import record_acquisition_failure

    if expired:
        pipeline.weather(
            pg,
            match,
            effective_at=ready["kickoff"],
            valid_until=datetime.now(UTC) - timedelta(milliseconds=100),
        )
    record_acquisition_failure(
        pg,
        match_id=match["id"],
        source_id="open_meteo",
        domain="weather",
        subject_key="forecast",
        status=AcquisitionStatus.QUOTA_EXHAUSTED,
        acquired_at=datetime.now(UTC),
    )
    pg.commit()
    assert release_input_update(pg, ready["claim"])
    pg.commit()
    ready["claim"] = updates.take(pg, ready["claim"].consumer_key)
    ready = rebuild(pg, ready, match)
    result = read(pg, complete(pg, ready))
    assert result["decision"]["mode"] == ("market_reference" if expired else "basic")
    assert result["decision"]["model_independent"] is (not expired)


def test_noop_official_update_does_not_invalidate(pg, ready, match):
    identifier = complete(pg, ready)
    query(pg, "UPDATE official_matches SET sale_status=sale_status WHERE id=%s", (match["id"],))
    pg.commit()
    assert read(pg, identifier)["recommendation_eligible"]


def test_old_research_revision_stays_closed_after_real_reopening(pg, ready, match):
    query(pg, "UPDATE official_matches SET sale_status='closed' WHERE id=%s", (match["id"],))
    pg.commit()
    assert release_input_update(pg, ready["claim"])
    pg.commit()
    ready["claim"] = updates.take(pg, ready["claim"].consumer_key)
    ready = rebuild(pg, ready, match)
    identifier = complete(pg, ready)
    query(pg, "UPDATE official_matches SET sale_status='selling' WHERE id=%s", (match["id"],))
    pg.commit()
    result = read(pg, identifier)
    assert result["research_only"] and not result["recommendation_eligible"]


def test_exact_batch_for_other_match_is_rejected(pg, ready, match):
    other = dict(match, id=obs_match_id(pg))
    bad = rebuild(pg, ready, other)
    with pytest.raises(ValueError, match="claimed match"):
        complete(pg, bad)
    pg.rollback()


def obs_match_id(pg):
    return pipeline.match_id.__wrapped__(pg)


def test_consumer_contract_remains_one_result_per_version(pg, ready):
    identifier = complete(pg, ready)
    # Changing play on replay cannot generate another result under an old key.
    assert complete(pg, ready, play_type="rqspf") == identifier


def test_trigger_security_boundary(pg):
    row = query(
        pg,
        "SELECT prosecdef,proconfig,has_function_privilege('fqp_observation_writer',oid,'EXECUTE') "
        "FROM pg_proc WHERE oid='notify_prediction_official_update()'::regprocedure",
    )[0]
    assert row == (True, ["search_path=pg_catalog"], False)


def test_closed_research_expiry_does_not_create_endless_recompute(pg, ready, match):
    query(pg, "UPDATE official_matches SET sale_status='closed' WHERE id=%s", (match["id"],))
    pg.commit()
    assert release_input_update(pg, ready["claim"])
    pg.commit()
    ready["claim"] = updates.take(pg, ready["claim"].consumer_key)
    ready = rebuild(pg, ready, match)
    identifier = complete(pg, ready, max_age_seconds=1)
    query(pg, "SELECT pg_sleep(1.05)")
    assert read(pg, identifier)["research_only"]
    assert claim_prediction_input_revisions(pg, consumer_key=ready["claim"].consumer_key) == []
    pg.rollback()


def test_quota_failure_recovery_and_sale_close_keep_versioned_history(pg, ready, match):
    """One controlled pilot lifecycle; synthetic profile is not a live artifact."""
    from scripts.data_contracts import AcquisitionStatus
    from scripts.observation_storage import record_acquisition_failure

    def publish_current(state, *, first=False):
        if not first:
            query(pg, "SET ROLE fqp_input_consumer")
            state = dict(state, claim=updates.take(pg, state["claim"].consumer_key))
            query(pg, "RESET ROLE")
            pg.commit()
            state = rebuild(pg, state, match)
        query(pg, "SET ROLE fqp_input_consumer")
        identifier = complete(pg, state)
        assert complete(pg, state) == identifier
        current = read(pg, identifier)
        query(pg, "RESET ROLE")
        pg.commit()
        return state, current

    ready, first = publish_current(ready, first=True)
    assert first["decision"]["mode"] == "basic" and first["recommendation_eligible"]
    original_decision = first["decision"]
    before = updates.head(pg, match["id"])[0]
    pipeline.weather(
        pg,
        match,
        12,
        effective_at=ready["kickoff"],
        valid_until=datetime.now(UTC) - timedelta(milliseconds=100),
    )
    query(pg, "SET ROLE fqp_observation_writer")
    check = record_acquisition_failure(
        pg,
        match_id=match["id"],
        source_id="open_meteo",
        domain="weather",
        subject_key="forecast",
        status=AcquisitionStatus.QUOTA_EXHAUSTED,
        acquired_at=datetime.now(UTC),
    )
    # Notification exists in the same writer transaction, without UPDATE rights.
    query(pg, "RESET ROLE")
    assert updates.head(pg, match["id"]) == (before + 2, check)
    pg.commit()
    assert not read(pg, first["id"])["recommendation_eligible"]
    ready, degraded = publish_current(ready)
    assert degraded["decision"]["mode"] == "market_reference"
    assert not degraded["decision"]["model_independent"]
    assert not degraded["recommendation_eligible"]

    pipeline.weather(pg, match, 19, effective_at=ready["kickoff"])
    ready, recovered = publish_current(ready)
    assert recovered["decision"]["mode"] == "basic" and recovered["recommendation_eligible"]
    assert not read(pg, degraded["id"])["recommendation_eligible"]
    assert read(pg, first["id"])["decision"] == original_decision

    query(pg, "UPDATE official_matches SET sale_status='closed' WHERE id=%s", (match["id"],))
    pg.commit()
    assert not read(pg, recovered["id"])["recommendation_eligible"]
    ready, closed = publish_current(ready)
    assert closed["research_only"] and not closed["recommendation_eligible"]
    query(pg, "UPDATE official_matches SET sale_status='selling' WHERE id=%s", (match["id"],))
    pg.commit()
    assert not read(pg, closed["id"])["recommendation_eligible"]
    ids = [row["id"] for row in (first, degraded, recovered, closed)]
    assert len(set(ids)) == 4
    assert query(
        pg,
        "SELECT count(*) FROM prediction_input_consumptions WHERE consumer_key=%s AND match_id=%s",
        (ready["claim"].consumer_key, match["id"]),
    ) == [(4,)]
