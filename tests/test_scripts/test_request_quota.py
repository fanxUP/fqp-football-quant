"""Fixed quota cases; Redis cases require the explicitly isolated test URL."""

from __future__ import annotations

import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from redis import Redis

from scripts.request_quota import QuotaDenied, QuotaPolicy, QuotaUnavailable, RedisQuotaLedger


def policy(**changes):
    return QuotaPolicy(
        **{
            "provider": "api_football",
            "account_scope": uuid4().hex,
            "daily_limit": 20,
            "minute_limit": 20,
            "environment_limits": (("development", 10), ("production", 10)),
            **changes,
        }
    )


@pytest.fixture
def client():
    url = os.getenv("FQP_QUOTA_TEST_REDIS_URL")
    if not url:
        pytest.skip("isolated Redis URL not supplied; never use application REDIS_URL")
    instance = Redis.from_url(url, decode_responses=True, socket_timeout=2)
    assert instance.ping()
    yield instance
    instance.close()


def ledger(client, *, provision=True, environment="production", **changes):
    instance = RedisQuotaLedger(client, policy(**changes), environment=environment)
    if provision:
        instance.provision(
            daily_usage=dict.fromkeys(dict(instance.policy.environment_limits), 0), minute_usage=0
        )
    return instance


def denied(reason, action):
    with pytest.raises(QuotaDenied) as exc:
        action()
    assert exc.value.reason == reason
    return exc.value


@pytest.mark.parametrize(
    "changes",
    [
        {"daily_limit": -1},
        {"daily_limit": True},
        {"daily_limit": 10_001},
        {"minute_limit": -1},
        {"minute_limit": 1.5},
        {"environment_limits": (("production", 21),)},
        {"environment_limits": (("production", 1), ("production", 1))},
        {"environment_limits": ()},
        {"environment_limits": (("production", -1),)},
        {"priority_reserve": 21},
        {"priority_reserve": -1},
        {"day_reset_offset_seconds": 86_400},
        {"day_reset_offset_seconds": -1},
        {"minimum_interval_ms": -1},
        {"lease_ms": 0},
        {"lease_ms": 60_001},
        {"provider": "https://bad"},
        {"account_scope": "secret key with spaces"},
    ],
)
def test_policy_rejects_unsafe_or_ambiguous_budget(changes):
    with pytest.raises(ValueError):
        policy(**changes)


def test_policy_is_immutable_and_environment_order_is_canonical():
    p = policy()
    assert p.environment_limits == tuple(sorted(p.environment_limits))
    with pytest.raises(AttributeError):
        p.daily_limit = 999


def test_missing_ledger_never_initializes_on_request(client):
    book = ledger(client, provision=False)
    denied("ledger_missing", book.reserve)
    assert not client.exists(book.key)


def test_provision_requires_all_known_usage_and_never_overwrites(client):
    book = ledger(client, provision=False)
    with pytest.raises(ValueError):
        book.provision(daily_usage={"production": 0}, minute_usage=0)
    book.provision(daily_usage={"production": 3, "development": 2}, minute_usage=2)
    assert book.snapshot()["day_used"] == 5
    denied(
        "ledger_exists",
        lambda: book.provision(daily_usage={"production": 0, "development": 0}, minute_usage=0),
    )
    assert book.snapshot()["day_used"] == 5


@pytest.mark.parametrize(
    "usage,minute",
    [
        ({"production": -1, "development": 0}, 0),
        ({"production": True, "development": 0}, 0),
        ({"production": 11, "development": 0}, 0),
        ({"production": 1, "development": 0}, 21),
        ({"production": 0, "development": 0}, -1),
        ({"production": 1, "development": 0}, 2),
    ],
)
def test_invalid_provision_usage_rejected_before_redis(client, usage, minute):
    book = ledger(client, provision=False)
    with pytest.raises(ValueError):
        book.provision(daily_usage=usage, minute_usage=minute)
    assert not client.exists(book.key)


def test_environment_does_not_split_account_ledger(client):
    prod = ledger(client)
    dev = RedisQuotaLedger(client, prod.policy, environment="development")
    other = RedisQuotaLedger(
        client, replace(prod.policy, account_scope=uuid4().hex), environment="production"
    )
    assert prod.key == dev.key != other.key
    prod.reserve()
    dev.reserve()
    assert prod.snapshot()["day_used"] == 2
    assert prod.snapshot()["environment_used"] == {"development": 1, "production": 1}


def test_unknown_environment_cannot_use_or_provision_account(client):
    with pytest.raises(ValueError):
        RedisQuotaLedger(client, policy(), environment="other")


def test_configuration_drift_does_not_create_another_budget(client):
    book = ledger(client)
    mismatch = RedisQuotaLedger(
        client, replace(book.policy, minute_limit=19), environment="production"
    )
    assert mismatch.key == book.key
    denied("policy_mismatch", mismatch.reserve)


def test_unsent_reservation_can_be_returned_once(client):
    book = ledger(client)
    token = book.reserve()
    assert book.snapshot()["day_used"] == 1
    assert book.cancel(token)
    assert not book.cancel(token)
    assert book.snapshot()["day_used"] == book.snapshot()["minute_used"] == 0


def test_sent_or_timeout_attempt_is_never_refunded_or_reused(client):
    book = ledger(client)
    token = book.reserve()
    receipt = book.mark_sent(token)
    assert receipt.day_sent == receipt.minute_sent == 1
    assert not book.cancel(token)
    denied("invalid_permit", lambda: book.mark_sent(token))
    for _ in range(2):  # Retries consume separate permits, even if every transport times out.
        book.mark_sent(book.reserve())
    assert book.snapshot()["day_used"] == book.snapshot()["day_sent"] == 3


def edit_state(client, book, mutate):
    value = json.loads(client.get(book.key))
    mutate(value)
    client.set(book.key, json.dumps(value))


def test_expired_unsent_permit_is_conservatively_charged(client):
    book = ledger(client)
    token = book.reserve()
    edit_state(client, book, lambda s: s["permits"][token].update(expires=0))
    denied("invalid_permit", lambda: book.mark_sent(token))
    assert not book.cancel(token)
    assert book.snapshot()["day_used"] == 1


def test_permit_cannot_be_used_or_cancelled_from_another_environment(client):
    book = ledger(client)
    dev = RedisQuotaLedger(client, book.policy, environment="development")
    token = book.reserve()
    denied("invalid_permit", lambda: dev.mark_sent(token))
    assert not dev.cancel(token)
    assert book.cancel(token)


@pytest.mark.parametrize("kind", ["missing", "invalid_json", "wrong_type", "expiring"])
def test_deleted_corrupt_or_expiring_ledger_stops_sending(client, kind):
    book = ledger(client)
    if kind == "missing":
        client.delete(book.key)
        denied("ledger_missing", book.reserve)
    elif kind == "invalid_json":
        client.set(book.key, "broken")
        denied("ledger_corrupt", book.reserve)
    elif kind == "wrong_type":
        client.delete(book.key)
        client.hset(book.key, "wrong", "type")
        with pytest.raises(QuotaUnavailable):
            book.reserve()
    else:
        client.expire(book.key, 3600)
        denied("ledger_expiring", book.reserve)


def test_redis_failure_does_not_return_a_permit_or_expose_url_secret():
    unavailable = Redis.from_url(
        "redis://:fixture-secret@127.0.0.1:1/0", socket_timeout=0.1, socket_connect_timeout=0.1
    )
    book = RedisQuotaLedger(unavailable, policy(), environment="production")
    with pytest.raises(QuotaUnavailable) as exc:
        book.reserve()
    assert "fixture-secret" not in str(exc.value)
    assert exc.value.__cause__ is None
    unavailable.close()


def test_clock_regression_does_not_open_an_old_window(client):
    book = ledger(client)
    edit_state(client, book, lambda s: s.update(last_time_ms=10**15))
    denied("clock_regression", book.reserve)


def test_only_new_day_resets_account_and_environment_budgets(client):
    book = ledger(client)
    token = book.reserve()
    book.release_priority_reserve()

    def previous_day(s):
        s["day"] -= 1
        for permit in s["permits"].values():
            permit["day"] -= 1
        s["day_used"] = 20
        s["day_sent"] = 20
        s["day_ceiling"] = 20
        s["environment_used"] = {"production": 10, "development": 10}

    edit_state(client, book, previous_day)
    book.reserve()
    state = book.snapshot()
    assert state["day_used"] == 1
    assert state["environment_used"] == {"production": 1, "development": 0}
    assert state["reserve_released"] is False
    denied("invalid_permit", lambda: book.mark_sent(token))


def test_minute_rollover_keeps_daily_usage(client):
    book = ledger(client, minute_limit=1)
    book.mark_sent(book.reserve())
    denied("minute_budget", book.reserve)
    edit_state(client, book, lambda s: s.update(minute=s["minute"] - 1))
    book.reserve()
    assert book.snapshot()["minute_used"] == 1
    assert book.snapshot()["day_used"] == 2


def test_minimum_interval_is_rechecked_atomically_at_send(client):
    book = ledger(client, minimum_interval_ms=60_000)
    one, two = book.reserve(), book.reserve()
    book.mark_sent(one)
    error = denied("minimum_interval", lambda: book.mark_sent(two))
    assert 0 < error.retry_after_ms <= 60_000
    assert book.cancel(two)


def test_priority_reserve_is_part_of_total_and_can_be_released(client):
    book = ledger(
        client,
        daily_limit=3,
        minute_limit=20,
        environment_limits=(("production", 3),),
        priority_reserve=1,
    )
    book.reserve()
    book.reserve()
    denied("priority_reserved", book.reserve)
    book.reserve(priority=True)
    denied("daily_budget", lambda: book.reserve(priority=True))
    other = ledger(
        client, daily_limit=2, environment_limits=(("production", 2),), priority_reserve=1
    )
    other.reserve()
    other.release_priority_reserve()
    other.reserve()
    denied("daily_budget", other.reserve)


def test_environment_allocation_cannot_borrow_from_other_environment(client):
    book = ledger(client, environment_limits=(("production", 1), ("development", 19)))
    book.reserve()
    denied("environment_budget", book.reserve)


@pytest.mark.parametrize(
    "field,reason",
    [("daily_remaining", "provider_daily_budget"), ("minute_remaining", "provider_minute_budget")],
)
def test_provider_zero_remaining_tightens_even_preexisting_reservations(client, field, reason):
    book = ledger(client)
    receipt = book.mark_sent(book.reserve())
    pending = book.reserve()
    book.apply_feedback(receipt, **{field: 0})
    denied(reason, lambda: book.mark_sent(pending))
    assert book.cancel(pending)
    denied(reason, book.reserve)


def test_feedback_uses_send_sequence_not_later_reservations_and_never_raises_ceiling(client):
    book = ledger(client)
    receipt = book.mark_sent(book.reserve())
    one, two = book.reserve(), book.reserve()
    book.apply_feedback(receipt, daily_remaining=1)
    assert book.snapshot()["day_ceiling"] == 2
    book.apply_feedback(receipt, daily_remaining=100)
    assert book.snapshot()["day_ceiling"] == 2
    book.mark_sent(one)
    denied("provider_daily_budget", lambda: book.mark_sent(two))


@pytest.mark.parametrize("reason", ["authentication_denied", "plan_denied"])
def test_401_403_style_block_survives_day_rollover(client, reason):
    book = ledger(client)
    receipt = book.mark_sent(book.reserve())
    book.apply_feedback(receipt, denied=reason)
    edit_state(client, book, lambda s: s.update(day=s["day"] - 1))
    denied(reason, book.reserve)


def test_429_style_cooldown_is_shared_and_cannot_be_shortened(client):
    book = ledger(client)
    receipt = book.mark_sent(book.reserve())
    book.apply_feedback(receipt, retry_after_ms=60_000)
    book.apply_feedback(receipt, retry_after_ms=1)
    clone = RedisQuotaLedger(client, book.policy, environment="production")
    assert denied("cooldown", clone.reserve).retry_after_ms > 50_000


def test_old_window_feedback_does_not_consume_new_day_budget(client):
    book = ledger(client)
    receipt = book.mark_sent(book.reserve())
    old = replace(receipt, day=receipt.day - 1, minute=receipt.minute - 1440)
    book.apply_feedback(old, daily_remaining=0, minute_remaining=0)
    assert book.snapshot()["day_ceiling"] == 20
    assert book.snapshot()["minute_ceiling"] == 20


def test_receipt_for_another_account_is_rejected(client):
    book = ledger(client)
    other = ledger(client)
    receipt = book.mark_sent(book.reserve())
    with pytest.raises(ValueError):
        other.apply_feedback(receipt, daily_remaining=0)
    assert other.snapshot()["day_ceiling"] == 20


def test_new_client_object_keeps_usage_and_no_request_resets_it(client):
    book = ledger(client)
    book.reserve()
    clone = RedisQuotaLedger(client, book.policy, environment="production")
    assert clone.snapshot()["day_used"] == 1
    clone.reserve()
    assert book.snapshot()["day_used"] == 2


def test_thread_competition_grants_only_minute_budget(client):
    book = ledger(client, minute_limit=7)

    def reserve(_):
        try:
            book.reserve()
            return 1
        except QuotaDenied:
            return 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(40))) == 7
    assert book.snapshot()["minute_used"] == 7


def process_competitor(url, quota_policy, environment):
    instance = Redis.from_url(url, decode_responses=True, socket_timeout=2)
    book = RedisQuotaLedger(instance, quota_policy, environment=environment)
    granted = 0
    for _ in range(15):
        try:
            book.reserve()
            granted += 1
        except QuotaDenied:
            pass
    instance.close()
    return granted


def test_independent_processes_share_account_and_environment_caps(client):
    book = ledger(
        client,
        daily_limit=13,
        minute_limit=20,
        environment_limits=(("production", 7), ("development", 6)),
    )
    with ProcessPoolExecutor(
        max_workers=4, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        futures = [
            pool.submit(
                process_competitor, os.environ["FQP_QUOTA_TEST_REDIS_URL"], book.policy, env
            )
            for env in ("production", "development", "production", "development")
        ]
        assert sum(f.result(timeout=20) for f in futures) == 13
    state = book.snapshot()
    assert state["day_used"] == 13
    assert state["environment_used"] == {"production": 7, "development": 6}


def test_non_midnight_reset_uses_redis_time_and_explicit_offset(client):
    book = ledger(client, day_reset_offset_seconds=3600)
    seconds, micros = client.time()
    expected = (seconds - 3600) // 86400
    assert book.snapshot()["day"] == expected


def test_zero_budget_is_disabled_not_unlimited(client):
    book = ledger(client, daily_limit=0, minute_limit=0, environment_limits=(("production", 0),))
    denied("daily_budget", book.reserve)


@pytest.mark.parametrize(
    "corruption",
    [
        "negative",
        "fractional",
        "sent_exceeds_used",
        "environment_sum",
        "invalid_block",
        "invalid_permit",
    ],
)
def test_corrupt_numeric_or_permit_state_cannot_reopen_quota(client, corruption):
    book = ledger(client)
    token = book.reserve()

    def corrupt(s):
        if corruption == "negative":
            s["day_used"] = -1
        elif corruption == "fractional":
            s["minute_used"] = 0.5
        elif corruption == "sent_exceeds_used":
            s["day_sent"] = 2
        elif corruption == "environment_sum":
            s["environment_used"]["production"] = 0
        elif corruption == "invalid_block":
            s["blocked"] = "unrecognized"
        else:
            s["permits"][token]["expires"] = "later"

    edit_state(client, book, corrupt)
    denied("ledger_corrupt", book.reserve)


def test_nested_mutable_environment_input_is_frozen():
    allocations = [["production", 20]]
    p = policy(environment_limits=allocations)
    allocations[0][1] = 100
    assert p.environment_limits == (("production", 20),)


def test_feedback_rejects_malformed_send_sequence(client):
    book = ledger(client)
    receipt = book.mark_sent(book.reserve())
    with pytest.raises(ValueError):
        book.apply_feedback(replace(receipt, day_sent=True), daily_remaining=10)
