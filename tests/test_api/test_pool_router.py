"""Pool business contract and immutable-plan HTTP boundary tests."""

from contextlib import nullcontext
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from apps.backend.src.routers import pool

NOW = datetime(2026, 10, 27, 4, tzinfo=UTC)


def catalogue():
    fixtures = [
        {
            "match_order": i,
            "match_id": i + 100,
            "home_team": f"H{i}",
            "away_team": f"A{i}",
            "league": "test",
            "match_date": "2026-10-28T03:00:00+08:00",
        }
        for i in range(1, 15)
    ]
    return [
        {
            "id": n,
            "issue_no": "26100",
            "game_type": game,
            "source_game_type": game,
            "total_matches": 14,
            "raw_hash": f"hash-{game}",
            "raw_json": {"saleEndTime": stop},
            "fixtures": fixtures,
        }
        for n, game, stop in [(1, "t14c", "2026-10-27 23:00"), (2, "r9", "2026-10-27 22:00")]
    ]


@pytest.fixture
def runtime(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(pool, "get_db", lambda: nullcontext(conn))
    monkeypatch.setattr(pool, "business_now", lambda: NOW)
    monkeypatch.setattr(pool, "_catalogue", lambda *_: catalogue())
    return conn


def consensus(n):
    return {
        i + 100: {
            "vector": {"3": 0.4, "1": 0.35, "0": 0.25},
            "model_count": 1,
            "disagreement": None,
            "models": [],
        }
        for i in range(1, n + 1)
    }


def test_ten_predictions_enable_rx9_but_not_sf14(client, runtime, monkeypatch):
    calls = []

    def reader(conn, cutoffs, **kwargs):
        calls.append(cutoffs)
        return consensus(10)

    monkeypatch.setattr(pool, "_read_pool_model_consensus", reader)
    response = client.get("/api/pool/analyze")
    assert response.status_code == 200
    data = response.json()
    assert data["sf14_status"] == "missing_predictions"
    assert data["rx9_status"] == "ready"
    assert len(data["missing_inputs"]) == 4
    assert data["rx9"]["total_cost"] == 256
    assert data["probabilities"]["hit14_prob"] is None
    assert len(calls) == 2
    assert all(c == NOW for c in calls[0].values())
    assert not runtime.commit.called
    assert (
        "REPEATABLE READ READ ONLY"
        in runtime.cursor.return_value.__enter__.return_value.execute.call_args_list[0].args[0]
    )


def test_each_game_uses_its_official_stop_before_selecting_groups(client, runtime, monkeypatch):
    issues = catalogue()
    issues[0]["raw_json"] = {"saleEndTime": "2026-10-27 10:00"}
    issues[1]["raw_json"] = {"saleEndTime": "2026-10-27 11:00"}
    monkeypatch.setattr(pool, "_catalogue", lambda *_: issues)
    calls = []

    def reader(conn, cutoffs, **kw):
        calls.append((cutoffs, kw["historical"]))
        return consensus(8)

    monkeypatch.setattr(pool, "_read_pool_model_consensus", reader)
    result = client.get("/api/pool/analyze").json()
    assert result["analysis_mode"] == "historical"
    assert all(c.isoformat() == "2026-10-27T10:00:00+08:00" for c in calls[0][0].values())
    assert all(c.isoformat() == "2026-10-27T11:00:00+08:00" for c in calls[1][0].values())
    assert calls[0][1] is True
    assert result["rx9_status"] == "missing_predictions"


def test_no_r9_evidence_cannot_reuse_sf14_deadline(client, runtime, monkeypatch):
    monkeypatch.setattr(pool, "_catalogue", lambda *_: catalogue()[:1])
    monkeypatch.setattr(pool, "_read_pool_model_consensus", lambda *a, **k: consensus(14))
    data = client.get("/api/pool/analyze").json()
    assert data["sf14_status"] == "ready" and data["rx9_status"] == "issue_pending"
    assert data["rx9"]["combinations_count"] == 0


def test_cutoff_unknown_keeps_research_vectors_but_no_actionable_plan(client, runtime, monkeypatch):
    issues = catalogue()
    for i in issues:
        i["raw_json"] = {"estimateDrawTime": "2026-10-27 22:00"}
    monkeypatch.setattr(pool, "_catalogue", lambda *_: issues)
    monkeypatch.setattr(pool, "_read_pool_model_consensus", lambda *a, **k: consensus(14))
    data = client.get("/api/pool/analyze").json()
    assert data["sf14_status"] == data["rx9_status"] == "cutoff_pending"
    assert data["full_combinations"]["count"] == 0
    assert len(data["matches"]) == 14
    assert data["matches"][0]["prob_home"] == 0.4


def test_absent_issue_is_normal_missing_data(client, runtime, monkeypatch):
    monkeypatch.setattr(pool, "_catalogue", lambda *_: [])
    data = client.get("/api/pool/analyze").json()
    assert data["sf14_status"] == "missing_issue"
    assert data["issue"] is None


@pytest.mark.parametrize(
    "query",
    [
        "budget=3",
        "budget=0",
        "budget=2.5",
        "budget=10002",
        "pinned_orders=1,1",
        "pinned_orders=1&excluded_orders=1",
        "strategy=garbage",
    ],
)
def test_invalid_parameters(client, query):
    assert client.get("/api/pool/analyze?" + query).status_code in (400, 422)


def test_changed_evidence_rejects_save_before_any_write(client, runtime, monkeypatch):
    monkeypatch.setattr(pool, "_analysis", lambda *a, **k: {"input_hash": "b" * 64})
    response = client.post(
        "/api/pool/plans",
        json={"issue_id": "1", "budget": 256, "strategy": "balanced", "input_hash": "a" * 64},
    )
    assert response.status_code == 409
    assert not runtime.commit.called
    assert not any(
        "INSERT" in c.args[0]
        for c in runtime.cursor.return_value.__enter__.return_value.execute.call_args_list
    )


def test_input_hash_is_stable_without_evidence_changes(client, runtime, monkeypatch):
    monkeypatch.setattr(pool, "_read_pool_model_consensus", lambda *a, **k: consensus(14))
    first = client.get("/api/pool/analyze").json()
    second = client.get("/api/pool/analyze").json()
    assert first["input_hash"] == second["input_hash"]
    third = client.get("/api/pool/analyze?budget=128").json()
    assert third["input_hash"] != first["input_hash"]


def test_sample_is_labeled_synthetic_and_has_no_monte_carlo():
    sample = pool.get_pool_sample()
    assert sample["synthetic"] is True
    assert sample["probability_method"] == "independent-exact-v1"
    assert "monte_carlo" not in sample


def test_explicit_rx9_issue_id_resolves_the_corresponding_official_period(
    client, runtime, monkeypatch
):
    monkeypatch.setattr(pool, "_read_pool_model_consensus", lambda *a, **k: consensus(10))
    result = client.get("/api/pool/analyze?issue_id=2")
    assert result.status_code == 200
    assert result.json()["rx9_status"] == "ready"
    assert result.json()["issue"]["id"] == 1
