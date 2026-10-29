"""Policy boundaries are tested against fixed HTTP responses, never the site."""

import json

import httpx
import pytest

from scripts.sources.titan007 import cli, client, store
from scripts.sources.titan007.client import AcquisitionStopped, TitanClient, acquisition_session
from scripts.titan007_data import cache_lock, run_collection


def transport_client(monkeypatch, handler):
    monkeypatch.setattr(TitanClient, "_throttle", lambda self: None)
    instance = TitanClient(delay=0, jitter=0)
    headers = dict(instance.session.headers)
    instance.session.close()
    instance.session = httpx.Client(transport=httpx.MockTransport(handler), headers=headers)
    return instance


def test_budget_is_shared_across_clients_and_stops_before_next_request(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, text="ok")

    with acquisition_session(tmp_path, max_requests=1) as budget:
        first = transport_client(monkeypatch, handler)
        second = transport_client(monkeypatch, handler)
        assert first.get("https://live.titan007.com/test") == "ok"
        with pytest.raises(AcquisitionStopped, match="预算"):
            second.get("https://live.titan007.com/test")
        assert budget.requests == 1
        assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 403, 429])
def test_access_denial_persists_cooldown_without_retries(tmp_path, monkeypatch, status):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(status, headers={"Retry-After": "7200"})

    with acquisition_session(tmp_path, max_requests=5):
        source = transport_client(monkeypatch, handler)
        with pytest.raises(AcquisitionStopped, match=f"HTTP {status}"):
            source.get("https://live.titan007.com/test")
    with pytest.raises(AcquisitionStopped, match="冷却"):
        with acquisition_session(tmp_path, max_requests=5):
            pytest.fail("must not start a new acquisition during cooldown")
    assert len(calls) == 1
    assert json.loads((tmp_path / "cooldown.json").read_text())["status"] == status


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/live.titan007.com",
        "https://live.titan007.com.evil.test/x",
        "file:///etc/passwd",
        "https://user:secret@live.titan007.com/x",
    ],
)
def test_unregistered_or_credentialed_address_is_rejected(tmp_path, monkeypatch, url):
    with acquisition_session(tmp_path, max_requests=1) as budget:
        source = transport_client(monkeypatch, lambda request: pytest.fail("must not send"))
        with pytest.raises(ValueError):
            source.get(url)
        assert budget.requests == 0


def test_redirect_is_not_followed(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    with acquisition_session(tmp_path) as budget:
        source = transport_client(monkeypatch, handler)
        with pytest.raises(AcquisitionStopped, match="重定向"):
            source.get("https://live.titan007.com/test")
        assert len(calls) == budget.requests == 1


def test_missing_optional_transport_is_reported_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "cffi_requests", None)
    with acquisition_session(tmp_path) as budget:
        source = transport_client(monkeypatch, lambda request: pytest.fail("must not send"))
        with pytest.raises(AcquisitionStopped, match="可选传输依赖"):
            source.get("https://zq.titan007.com/test")
        assert budget.requests == 0


def test_gbk_decode_uses_explicit_charset_and_preserves_zero():
    assert client.decode_body("零0：比赛".encode("gbk"), "text/html; charset=gbk") == "零0：比赛"


def test_batch_policy_stop_reaches_project_entry_and_is_audited(tmp_path, monkeypatch):
    def blocked(self, *args, **kwargs):
        raise AcquisitionStopped("fixture source blocked")

    monkeypatch.setattr(TitanClient, "get", blocked)
    result = run_collection(["history", "--start", "2026-10-01", "--end", "2026-10-02"], tmp_path)
    assert result["status"] == "blocked"
    assert result["exit_code"] == 3
    assert result["business_database_imported"] is False
    saved = json.loads(next((tmp_path / "runs").glob("*.json")).read_text())
    assert saved["reason"] == "fixture source blocked"
    assert saved["requests"] == 0


@pytest.mark.parametrize(
    "arguments",
    [
        ["live", "--loop"],
        ["watch"],
        ["history", "--start", "2026-01-01", "--end", "2026-04-01"],
        ["details", "--match-id", "0"],
        ["analysis", "--limit", "0"],
    ],
)
def test_project_entry_rejects_unbounded_or_invalid_batches(tmp_path, arguments):
    with pytest.raises(ValueError):
        run_collection(arguments, tmp_path / "not_created")
    assert not (tmp_path / "not_created").exists()


def test_entry_reports_http_failure_as_partial(tmp_path, monkeypatch):
    def job(args):
        source = transport_client(
            monkeypatch, lambda request: httpx.Response(500, text="unavailable")
        )
        try:
            source.get("https://live.titan007.com/test")
        except httpx.HTTPStatusError:
            pass
        return 0  # The original batch CLI sometimes reports per-match failures but returns 0.

    parser = cli.build_parser()
    parser.set_defaults()
    original_parse = parser.parse_args

    def parse(args):
        result = original_parse(args)
        result.func = job
        return result

    monkeypatch.setattr(parser, "parse_args", parse)
    monkeypatch.setattr(cli, "build_parser", lambda: parser)
    result = run_collection(["live"], tmp_path)
    assert result["status"] == "partial"
    assert result["exit_code"] == 1
    assert result["requests"] == result["failures"] == 1


def test_collection_lock_prevents_overlapping_writer(tmp_path):
    with cache_lock(tmp_path / "cache"):
        with pytest.raises(RuntimeError, match="已有"):
            with cache_lock(tmp_path / "cache"):
                pytest.fail("second writer must not acquire the cache")


def test_new_cache_has_all_temporal_metadata_columns(tmp_path):
    conn = store.connect(str(tmp_path / "new.db"))
    try:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(matches)")}
        assert {"season", "first_fetched_at", "source_published_at", "home_score_rt"} <= columns
        assert "announced_at" in {
            r["name"] for r in conn.execute("PRAGMA table_info(predicted_lineups)")
        }
    finally:
        conn.close()


def test_source_catalog_registers_method_without_approving_business_consumption():
    from scripts.data_catalog import get_data_source

    source = get_data_source("titan007")
    assert source["entrypoint"] == "scripts.titan007_data"
    assert source["runtime_scheduled"] is False
    assert source["account_verification"] == source["coverage_verification"] == "unknown"
    assert source["storage_role"] == "raw_source_cache_not_business_truth"


def test_successful_http_with_parse_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    monkeypatch.setattr(TitanClient, "get", lambda *args, **kwargs: "unrecognized source page")

    def broken(*args, **kwargs):
        raise ValueError("source structure changed")

    monkeypatch.setattr(cli.parsers, "parse_history_page", broken)
    result = run_collection(["history", "--start", "2026-10-01", "--end", "2026-10-01"], tmp_path)
    assert result["status"] == "partial"
    assert result["exit_code"] == 1
    assert result["operation_failures"] == 1


def test_protected_transport_sends_exactly_one_referer(tmp_path, monkeypatch):
    from types import SimpleNamespace

    captured = []

    def get(url, **kwargs):
        headers = kwargs["headers"]
        referers = [v for k, v in headers.items() if k.lower() == "referer"]
        captured.extend(referers)
        return httpx.Response(200, text="ok", request=httpx.Request("GET", url))

    monkeypatch.setattr(client, "cffi_requests", SimpleNamespace(get=get))
    with acquisition_session(tmp_path):
        source = transport_client(monkeypatch, lambda request: pytest.fail("wrong transport"))
        assert (
            source.get("https://zq.titan007.com/test", referer="https://zq.titan007.com/") == "ok"
        )
    assert captured == ["https://zq.titan007.com/"]


def test_same_host_redirect_is_bounded_and_uses_request_budget(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.path == "/old":
            return httpx.Response(302, headers={"Location": "/new"})
        return httpx.Response(200, text="source data")

    with acquisition_session(tmp_path, max_requests=2) as budget:
        source = transport_client(monkeypatch, handler)
        assert source.get("https://live.titan007.com/old") == "source data"
        assert budget.requests == 2
        assert budget.failures == 0
    assert calls == ["https://live.titan007.com/old", "https://live.titan007.com/new"]


def test_redirect_loop_stops_without_unlimited_requests(tmp_path, monkeypatch):
    with acquisition_session(tmp_path, max_requests=10) as budget:
        source = transport_client(
            monkeypatch, lambda request: httpx.Response(302, headers={"Location": "/loop"})
        )
        with pytest.raises(AcquisitionStopped, match="重定向"):
            source.get("https://live.titan007.com/loop")
        assert budget.requests == 4
