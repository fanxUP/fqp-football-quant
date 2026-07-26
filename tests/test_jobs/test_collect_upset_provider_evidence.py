from unittest.mock import MagicMock

from scripts.jobs import collect_upset_provider_evidence


def test_provider_collection_skips_cleanly_without_api_key(monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)

    result = collect_upset_provider_evidence._run_impl()

    assert result == {
        "status": "skipped",
        "quality_status": "unavailable",
        "reason": "API_FOOTBALL_KEY_NOT_CONFIGURED",
        "api_calls_used": 0,
    }


def test_provider_collection_defaults_to_free_plan_history_window(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-key")
    monkeypatch.delenv("UPSET_PROVIDER_EVIDENCE_LOOKBACK_DAYS", raising=False)
    captured: dict[str, int] = {}
    connection = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = connection

    class FakeClient:
        call_count_today = 0

        def __init__(self, **_kwargs):
            pass

        def close(self):
            pass

    def fake_load_pending_events(_conn, *, limit, lookback_days):
        captured["limit"] = limit
        captured["lookback_days"] = lookback_days
        return []

    monkeypatch.setattr(collect_upset_provider_evidence, "ApiFootballClient", FakeClient)
    monkeypatch.setattr(collect_upset_provider_evidence, "get_db", lambda: context)
    monkeypatch.setattr(
        collect_upset_provider_evidence,
        "_load_pending_events",
        fake_load_pending_events,
    )

    result = collect_upset_provider_evidence._run_impl()

    assert captured["lookback_days"] == 1
    assert result["quality_status"] == "not_due"
