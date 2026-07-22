from contextlib import contextmanager

from apps.backend.src.routers import competition


def test_decisions_endpoint_returns_recent_agent_decisions(monkeypatch):
    @contextmanager
    def fake_db():
        yield object()

    expected = [{"decisionDate": "2026-07-14", "status": "abstained"}]
    monkeypatch.setattr(competition, "get_db", fake_db)
    monkeypatch.setattr(
        competition,
        "list_agent_daily_decisions",
        lambda conn, limit: expected,
    )

    assert competition.get_agent_daily_decisions(limit=14) == {
        "decisions": expected,
        "total": 1,
    }
