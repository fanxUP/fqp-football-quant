"""Pool router performance and contract tests."""

from unittest.mock import MagicMock, patch

from apps.backend.src.routers import pool


def test_deterministic_pool_sample_is_computed_once(monkeypatch):
    calls = 0
    simulation_counts = []

    def fake_analyze(*args, **kwargs):
        nonlocal calls
        calls += 1
        simulation_counts.append(kwargs["n_mc_simulations"])
        return {"sample": True}

    monkeypatch.setattr(pool, "analyze_pool", fake_analyze)
    monkeypatch.setattr(pool, "pool_analysis_to_dict", lambda analysis: analysis)
    pool._build_pool_sample.cache_clear()

    assert pool.get_pool_sample() == {"sample": True}
    assert pool.get_pool_sample() == {"sample": True}
    assert calls == 1
    assert simulation_counts == [1_000]


def test_pool_analysis_uses_coherent_prematch_model_consensus(client):
    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = []

    with patch("apps.backend.src.routers.pool.get_db", return_value=conn):
        response = client.get("/api/pool/analyze")

    assert response.status_code == 404
    query = " ".join(cur.execute.call_args.args[0].split())
    assert "mp.predict_time < m.kickoff_time" in query
    assert "DISTINCT ON (mp.model_version_id, mp.option_code)" in query
    assert "AVG(model_probability) FILTER" in query


def test_pool_analysis_uses_latest_complete_official_issue_for_historical_review(client):
    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = [
        (
            279,
            "26092",
            "t14c",
            14,
            "closed",
            "2026-07-14 22:00:00",
            order,
            None,
            f"主队{order}",
            f"客队{order}",
            "测试联赛",
            "2026-07-15 02:00:00",
            1000 + order,
            "模型共识",
            0.45,
            0.30,
            0.25,
        )
        for order in range(1, 15)
    ]

    with (
        patch("apps.backend.src.routers.pool.get_db", return_value=conn),
        patch("apps.backend.src.routers.pool.analyze_pool", return_value={"computed": True}),
        patch(
            "apps.backend.src.routers.pool.pool_analysis_to_dict",
            return_value={"period_id": "26092-t14c"},
        ),
    ):
        response = client.get("/api/pool/analyze")

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis_mode"] == "historical"
    assert payload["issue"]["issue_no"] == "26092"
    assert payload["issue"]["status"] == "closed"
