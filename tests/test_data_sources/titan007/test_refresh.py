"""Fixed-response refresh tests: no real website, account or business database."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from scripts import titan007_refresh as refresh
from scripts.sources.titan007 import client

pytest_plugins = ("tests.test_data_sources.titan007.test_league_import",)


def season_js(*, missing_away=False, league_id=36):
    def ranking(scope):
        rows = []
        for rank, tid in enumerate([19, 24], 1):
            played = int(
                scope == "total"
                or (scope == "home" and tid == 19)
                or (scope == "away" and tid == 24)
            )
            row = [rank, tid, played, 0, played, 0, 0, 0, 0, "", "", "", 0, 0, played]
            if scope == "total":
                row = [0, *row[:2], 0, *row[2:]]
            rows.append(row)
        return rows

    variables = {
        "arrLeague": [
            league_id,
            "英超",
            "英超",
            "English Premier League",
            1,
            "",
            "",
            "英超",
            "英超",
            "",
        ],
        "arrTeam": [
            [19, "阿森纳", "阿森納", "Arsenal", "", ""],
            [24, "切尔西", "車路士", "Chelsea", "", ""],
        ],
        "totalScore": ranking("total"),
        "homeScore": ranking("home"),
        "guestScore": [] if missing_away else ranking("away"),
    }
    text = "\n".join(f"var {key}={json.dumps(value)};" for key, value in variables.items())
    for round_no, status, day, home, away, score in [
        (1, -1, "2026-10-20 20:00", 19, 24, "0-0"),
        (2, 0, "2026-11-20 20:00", 24, 19, ""),
    ]:
        row = [
            100 + round_no,
            league_id,
            status,
            day,
            home,
            away,
            score,
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
        text += f'\njh["R_{round_no}"]={json.dumps([row])};'
    return text + "\nvar lastUpdateTime='2026-10-29 10:00:00';"


@pytest.fixture
def website(monkeypatch):
    calls = []
    responses = {"js": season_js(), "status": 200}

    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(
            responses["status"],
            text=responses["js"] if ".js" in url else "SubSclassID = 1;",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(client, "cffi_requests", SimpleNamespace(get=get))
    monkeypatch.setattr(client.TitanClient, "_throttle", lambda self: None)
    monkeypatch.setattr(refresh, "now_utc", lambda: datetime(2026, 10, 29, 8, tzinfo=UTC))
    return calls, responses


def test_refresh_freezes_whole_season_without_touching_historical_cache(tmp_path, config, website):
    database = tmp_path / "titan007.db"
    database.write_bytes(b"historical copy must not be opened or overwritten")
    result = refresh.refresh_league(tmp_path, config=config)
    assert result["status"] == "ready" and result["requests"] == 2
    assert result["business_database_imported"] is False
    payload = json.loads(
        (tmp_path / "runs" / f"refresh-{result['run_id']}.payload.json").read_text()
    )
    assert payload["source_as_of"] == "2026-10-29T02:00:00+00:00"
    assert datetime.fromisoformat(payload["source_acquired_at"]).tzinfo is not None
    assert payload["fixtures"][0]["homeGoals"] == 0
    assert payload["fixtures"][1]["homeGoals"] is None
    assert database.read_bytes() == b"historical copy must not be opened or overwritten"
    assert len(website[0]) == 2 and not any("Archer" in url for url in website[0])
    assert not list(tmp_path.glob(".refresh-*"))


def test_new_refresh_waits_six_hours_but_resume_never_fetches(tmp_path, config, website):
    first = refresh.refresh_league(tmp_path, config=config)
    second = refresh.refresh_league(tmp_path, config=config)
    assert second["status"] == "blocked" and second["requests"] == 0
    resumed = refresh.refresh_league(tmp_path, config=config, resume=first["run_id"])
    assert resumed["status"] == "ready" and resumed["requests_this_attempt"] == 0
    assert resumed["source_content_sha256"] == first["source_content_sha256"]
    assert len(website[0]) == 2


def test_next_allowed_refresh_keeps_content_key_but_has_new_acquisition_receipt(
    tmp_path, config, website, monkeypatch
):
    from datetime import timedelta

    first = refresh.refresh_league(tmp_path, config=config)
    later = refresh.now_utc() + timedelta(hours=7)
    monkeypatch.setattr(refresh, "now_utc", lambda: later)
    second = refresh.refresh_league(tmp_path, config=config)
    assert second["status"] == "ready" and len(website[0]) == 4
    assert second["run_id"] != first["run_id"]
    assert second["source_acquired_at"] != first["source_acquired_at"]
    assert second["source_content_sha256"] == first["source_content_sha256"]
    assert second["payload_sha256"] != first["payload_sha256"]


@pytest.mark.parametrize("failure", ["missing_away", "wrong_league", "bad_time", "stale"])
def test_incomplete_or_wrong_source_is_not_prepared_or_published(
    tmp_path, config, website, failure
):
    calls, responses = website
    responses["js"] = season_js(
        missing_away=failure == "missing_away", league_id=25 if failure == "wrong_league" else 36
    )
    if failure == "bad_time":
        responses["js"] = responses["js"].replace("2026-10-29 10:00:00", "unknown")
    if failure == "stale":
        responses["js"] = responses["js"].replace("2026-10-29 10:00:00", "2020-01-01 00:00:00")
    result = refresh.refresh_league(tmp_path, config=config)
    assert result["status"] == "failed" and result["exit_code"] != 0
    assert not list((tmp_path / "runs").glob("*.payload.json"))
    assert result["business_database_imported"] is False and len(calls) == 2


@pytest.mark.parametrize("status", [401, 403, 429])
def test_denial_or_budget_never_publishes_partial_data(tmp_path, config, website, status):
    website[1]["status"] = status
    result = refresh.refresh_league(tmp_path, config=config)
    assert result["status"] == "blocked" and result["requests"] == 1
    assert not list((tmp_path / "runs").glob("*.payload.json"))
    assert (tmp_path / "cooldown.json").exists()


def test_request_exhaustion_keeps_audited_receipt_without_payload(tmp_path, config, website):
    result = refresh.refresh_league(tmp_path, config=config, max_requests=1)
    assert result["status"] == "blocked" and result["requests"] == 1
    assert not list((tmp_path / "runs").glob("*.payload.json"))
    assert (
        json.loads((tmp_path / "runs" / f"refresh-{result['run_id']}.json").read_text())[
            "exit_code"
        ]
        == 3
    )


@pytest.mark.parametrize("mutation", ["bytes", "config", "path"])
def test_resume_rejects_tampered_payload_or_scope(tmp_path, config, website, mutation):
    first = refresh.refresh_league(tmp_path, config=config)
    if mutation == "bytes":
        path = tmp_path / "runs" / f"refresh-{first['run_id']}.payload.json"
        path.write_text(path.read_text().replace('"Arsenal"', '"Other"'))
    if mutation == "config":
        config = {**config, "season": "2025-2026"}
    result = refresh.refresh_league(
        tmp_path, config=config, resume="../../escape" if mutation == "path" else first["run_id"]
    )
    assert result["status"] == "failed" and result["business_database_imported"] is False
    assert len(website[0]) == 2


def test_publish_failure_is_retryable_without_network_and_does_not_log_credentials(
    tmp_path, config, website, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:private-password@127.0.0.1/test")

    def failure(*args):
        raise RuntimeError("private-password")

    monkeypatch.setattr(refresh, "publish_payload", failure)
    failed = refresh.refresh_league(tmp_path, config=config, apply=True)
    assert failed["status"] == "publish_failed" and failed["requests"] == 2
    assert "private-password" not in json.dumps(failed)
    monkeypatch.setattr(
        refresh, "publish_payload", lambda *args: {"status": "published", "batch_id": 9}
    )
    done = refresh.refresh_league(tmp_path, config=config, apply=True, resume=failed["run_id"])
    assert done["status"] == "published" and done["publication"]["batch_id"] == 9
    assert done["requests_this_attempt"] == 0 and len(website[0]) == 2


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "postgresql://x:secret@remote/test",
        "host=127.0.0.1,remote dbname=test",
        "service=production host=127.0.0.1",
    ],
)
def test_apply_validates_explicit_local_database_before_any_request(
    tmp_path, config, website, monkeypatch, dsn
):
    monkeypatch.setenv("DATABASE_URL", dsn)
    result = refresh.refresh_league(tmp_path, config=config, apply=True)
    assert result["status"] == "failed" and website[0] == []
    assert "secret" not in json.dumps(result)


def test_shared_daily_limit_survives_new_sessions_and_fails_closed(tmp_path, monkeypatch):
    day = datetime.now(UTC).date().isoformat()
    ledger = tmp_path / "daily-usage.json"
    ledger.write_text(json.dumps({"day": day, "requests": 99}))
    calls = []
    monkeypatch.setattr(client.TitanClient, "_throttle", lambda self: None)
    with client.acquisition_session(tmp_path) as first:
        instance = client.TitanClient()
        instance.session.close()
        instance.session = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: calls.append(request) or httpx.Response(200, text="ok")
            )
        )
        instance.get("https://live.titan007.com/test")
    assert first.requests == 1
    with pytest.raises(client.AcquisitionStopped, match="每日"):
        with client.acquisition_session(tmp_path):
            pytest.fail("daily cap must apply before constructing a new client")
    assert len(calls) == 1 and json.loads(ledger.read_text())["requests"] == 100
    ledger.write_text("{broken")
    with pytest.raises(client.AcquisitionStopped, match="账本"):
        with client.acquisition_session(tmp_path):
            pytest.fail("corrupt budget must not silently reset")


def test_acquisition_time_does_not_create_a_different_content_revision(cache, config):
    from scripts.titan007_import import load_season, season_content_hash

    data = load_season(cache, config=config)
    original = data["content_sha256"]
    data["source_acquired_at"] = "2026-10-29T08:00:00+00:00"
    assert season_content_hash(data) == original
    data["fixtures"][0]["homeGoals"] = 2
    assert season_content_hash(data) != original


def test_utc_day_rollover_resets_usage_and_transport_failure_still_consumes_one(
    tmp_path, monkeypatch
):
    from datetime import timedelta

    ledger = tmp_path / "daily-usage.json"
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    ledger.write_text(json.dumps({"day": yesterday, "requests": 100}))
    monkeypatch.setattr(client.TitanClient, "_throttle", lambda self: None)

    def unavailable(request):
        raise httpx.ConnectError("fixed response failure")

    with client.acquisition_session(tmp_path) as budget:
        instance = client.TitanClient()
        instance.session.close()
        instance.session = httpx.Client(transport=httpx.MockTransport(unavailable))
        with pytest.raises(httpx.ConnectError):
            instance.get("https://live.titan007.com/test")
    assert budget.failures == budget.requests == 1
    assert json.loads(ledger.read_text()) == {
        "day": datetime.now(UTC).date().isoformat(),
        "requests": 1,
    }
