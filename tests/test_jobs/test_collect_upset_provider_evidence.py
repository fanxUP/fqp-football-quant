from scripts.jobs.collect_upset_provider_evidence import _run_impl


def test_provider_collection_skips_cleanly_without_api_key(monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)

    result = _run_impl()

    assert result == {
        "status": "skipped",
        "quality_status": "unavailable",
        "reason": "API_FOOTBALL_KEY_NOT_CONFIGURED",
        "api_calls_used": 0,
    }
