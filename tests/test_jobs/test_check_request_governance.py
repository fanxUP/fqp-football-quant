"""Fixed operational checks; no application URL, provider calls or database."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from redis.exceptions import ConnectionError

from scripts.jobs import check_request_governance as job

PREFIX = "fqp:request-reuse:v1:"
KEY = PREFIX + "{" + "a" * 64 + "}"
NOW = 1_700_000_000_000


def client():
    instance = Mock()
    instance.info.side_effect = lambda section: {
        "persistence": {
            "aof_enabled": 1,
            "aof_last_write_status": "ok",
            "aof_last_bgrewrite_status": "ok",
            "loading": 0,
        },
        "replication": {"role": "master"},
        "memory": {"used_memory": 1000, "used_memory_rss": 2000},
        "stats": {"evicted_keys": 0},
    }[section]
    instance.config_get.return_value = {
        "appendonly": "yes",
        "appendfsync": "always",
        "maxmemory": "67108864",
        "maxmemory-policy": "noeviction",
        "stop-writes-on-bgsave-error": "yes",
    }
    instance.acl_getuser.return_value = {"flags": ["off"], "passwords": ["hidden"]}
    instance.time.return_value = (NOW // 1000, 0)
    instance.scan.return_value = (0, [])
    return instance


def running(instance, *, age=1000, ttl=-1, **changes):
    instance.scan.return_value = (0, [KEY])
    instance.pttl.return_value = ttl
    instance.getrange.return_value = json.dumps(
        {
            "schema": "request-reuse/v1",
            "state": "running",
            "token": "sensitive-owner",
            "started_at_ms": NOW - age,
            **changes,
        }
    )


def test_good_observation_never_certifies_live_account_or_deployment():
    c = client()
    report = job.inspect_redis(c)
    assert report["status"] == "ok"
    assert report["activation_verified"] is False
    assert report["read_only"] is True
    assert report["owners"]["scan_complete"] is True
    assert report["point_in_time_consistency"] is False
    assert report["issues"] == []
    allowed = {"info", "config_get", "acl_getuser", "time", "scan", "pttl", "getrange"}
    assert {call[0] for call in c.method_calls} <= allowed


@pytest.mark.parametrize(
    "field,value,issue",
    [
        ("appendonly", "no", "persistence_configuration"),
        ("appendfsync", "everysec", "persistence_configuration"),
        ("maxmemory", "0", "memory_configuration"),
        ("maxmemory-policy", "allkeys-lru", "memory_configuration"),
        ("stop-writes-on-bgsave-error", "no", "persistence_configuration"),
    ],
)
def test_unsafe_configuration_has_fixed_issue(field, value, issue):
    c = client()
    c.config_get.return_value[field] = value
    report = job.inspect_redis(c)
    assert report["status"] == "attention"
    assert issue in report["issues"]


@pytest.mark.parametrize(
    "section,change,issue",
    [
        ("persistence", {"aof_enabled": 0}, "persistence_health"),
        ("persistence", {"aof_last_write_status": "err"}, "persistence_health"),
        ("persistence", {"loading": 1}, "persistence_health"),
        ("replication", {"role": "slave"}, "not_primary"),
        ("stats", {"evicted_keys": 1}, "historical_evictions"),
        ("memory", {"used_memory": 65_000_000}, "memory_pressure"),
    ],
)
def test_health_issues_are_not_ignored(section, change, issue):
    c = client()
    previous = c.info.side_effect
    c.info.side_effect = lambda name: {**previous(name), **(change if name == section else {})}
    assert issue in job.inspect_redis(c)["issues"]


def test_enabled_default_user_needs_access_review():
    c = client()
    c.acl_getuser.return_value = {"flags": ["on", "nopass"], "passwords": ["never-output"]}
    report = job.inspect_redis(c)
    assert "default_user_enabled" in report["issues"]
    assert "never-output" not in json.dumps(report)


@pytest.mark.parametrize("age,uncertain", [(1000, 0), (120_000, 1), (300_000, 1), (-1, 1)])
def test_running_age_and_clock_anomaly_are_visible_without_token(age, uncertain):
    c = client()
    running(c, age=age)
    report = job.inspect_redis(c)
    assert report["owners"]["running"] == 1
    assert report["owners"]["uncertain"] == uncertain
    assert ("uncertain_owners" in report["issues"]) == bool(uncertain)
    assert "sensitive-owner" not in json.dumps(report)
    assert KEY not in json.dumps(report)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema": "bad"},
        {"state": "success"},
        {"token": ""},
        {"started_at_ms": True},
        {"started_at_ms": 1.5},
    ],
)
def test_invalid_persistent_records_require_attention(changes):
    c = client()
    running(c, **changes)
    report = job.inspect_redis(c)
    assert report["owners"]["invalid"] == 1
    assert "invalid_owner_records" in report["issues"]


def test_expiring_results_are_not_read_and_disappeared_keys_are_counted():
    c = client()
    running(c, ttl=100)
    assert job.inspect_redis(c)["owners"]["expiring"] == 1
    c.getrange.assert_not_called()
    c.pttl.return_value = -2
    assert job.inspect_redis(c)["owners"]["disappeared"] == 1


def test_completed_owner_race_does_not_become_invalid_record():
    c = client()
    running(c, state="success", body="secret-response")
    c.pttl.side_effect = [-1, 1000]
    report = job.inspect_redis(c)
    assert report["owners"]["changed"] == 1
    assert report["owners"]["invalid"] == 0
    assert "secret-response" not in json.dumps(report)


def test_oversize_or_broken_json_is_bounded_and_not_printed():
    c = client()
    running(c)
    c.getrange.return_value = "secret-body" * 500
    report = job.inspect_redis(c)
    assert report["owners"]["invalid"] == 1
    c.getrange.assert_called_once_with(KEY, 0, 4095)
    assert "secret-body" not in json.dumps(report)


@pytest.mark.parametrize("token", ["synthetic", "汉" * 1000])
def test_valid_json_prefix_at_read_cap_is_still_incomplete(token):
    c = client()
    running(c, token=token)
    value = json.dumps(json.loads(c.getrange.return_value), ensure_ascii=False)
    c.getrange.return_value = value + " " * (4096 - len(value.encode("utf-8")))
    assert job.inspect_redis(c)["owners"]["invalid"] == 1


def test_owner_age_uses_clock_after_record_read():
    c = client()
    running(c)
    assert job.inspect_redis(c)["owners"]["max_age_ms"] == 1000
    calls = [call[0] for call in c.method_calls]
    assert calls.index("getrange") < calls.index("time")


def test_scan_deduplicates_and_page_limit_reports_incomplete():
    c = client()
    running(c)
    c.scan.return_value = (7, [KEY, KEY])
    report = job.inspect_redis(c, max_pages=2)
    assert report["owners"]["inspected"] == 1
    assert report["owners"]["pages"] == 2
    assert report["owners"]["scan_complete"] is False
    assert "owner_scan_incomplete" in report["issues"]
    assert report["status"] == "unavailable"


def test_key_limit_never_claims_complete_scan():
    c = client()
    running(c)
    c.scan.return_value = (0, [KEY, PREFIX + "{" + "b" * 64 + "}"])
    report = job.inspect_redis(c, max_keys=1)
    assert report["owners"]["inspected"] == 1
    assert report["owners"]["scan_complete"] is False


def test_unexpected_key_names_are_not_read_or_printed():
    c = client()
    c.scan.return_value = (0, [PREFIX + "secret-query"])
    report = job.inspect_redis(c)
    assert "invalid_owner_records" in report["issues"]
    c.getrange.assert_not_called()
    assert "secret-query" not in json.dumps(report)


def test_redis_failure_reports_only_fixed_code():
    c = client()
    c.info.side_effect = ConnectionError("redis://user:password@host secret-token")
    report = job.inspect_redis(c)
    assert report["status"] == "unavailable"
    assert report["issues"] == ["redis_read_unavailable"]
    assert "password" not in json.dumps(report)


def test_missing_url_never_reads_application_fallback(monkeypatch, capsys):
    monkeypatch.delenv("FQP_REQUEST_RUNTIME_REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://secret@production")
    factory = Mock()
    monkeypatch.setattr(job.Redis, "from_url", factory)
    assert job.main() == 2
    factory.assert_not_called()
    assert json.loads(capsys.readouterr().out)["issues"] == ["runtime_url_missing"]


def test_cli_closes_client_and_returns_attention_exit(monkeypatch, capsys):
    c = client()
    running(c, age=300_000)
    monkeypatch.setenv("FQP_REQUEST_RUNTIME_REDIS_URL", "redis://observer:secret@localhost/15")
    monkeypatch.setattr(job.Redis, "from_url", Mock(return_value=c))
    assert job.main() == 1
    c.close.assert_called_once()
    assert "secret" not in capsys.readouterr().out


def test_deadline_stops_before_unbounded_scanning(monkeypatch):
    c = client()
    ticks = iter([0, 10])
    monkeypatch.setattr(job.time, "monotonic", lambda: next(ticks))
    report = job.inspect_redis(c)
    assert report["status"] == "unavailable"
    assert report["issues"] == ["read_deadline"]
    c.info.assert_not_called()


def test_close_failure_does_not_expose_connection_secret(monkeypatch, capsys):
    c = client()
    c.close.side_effect = ConnectionError("secret-credential")
    monkeypatch.setenv("FQP_REQUEST_RUNTIME_REDIS_URL", "redis://observer:secret@localhost/15")
    monkeypatch.setattr(job.Redis, "from_url", Mock(return_value=c))
    assert job.main() == 2
    assert "secret-credential" not in capsys.readouterr().out


def test_incomplete_scan_cli_exit_is_two(monkeypatch, capsys):
    c = client()
    c.scan.return_value = (5, [])
    monkeypatch.setenv("FQP_REQUEST_RUNTIME_REDIS_URL", "redis://observer:secret@localhost/15")
    monkeypatch.setattr(job.Redis, "from_url", Mock(return_value=c))
    assert job.main() == 2
    assert "owner_scan_incomplete" in json.loads(capsys.readouterr().out)["issues"]


@pytest.mark.parametrize(
    "url",
    ["redis://localhost/0", "https://user:pass@host", "redis://u:p@host/0?socket_timeout=900"],
)
def test_cli_rejects_unauthenticated_or_override_urls(monkeypatch, capsys, url):
    monkeypatch.setenv("FQP_REQUEST_RUNTIME_REDIS_URL", url)
    factory = Mock()
    monkeypatch.setattr(job.Redis, "from_url", factory)
    assert job.main() == 2
    factory.assert_not_called()
    assert json.loads(capsys.readouterr().out)["issues"] == ["runtime_check_unavailable"]
