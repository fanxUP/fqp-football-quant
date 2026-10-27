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


def test_pool_analysis_without_official_issues_does_not_read_predictions(client):
    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = []

    with patch("apps.backend.src.routers.pool.get_db", return_value=conn):
        response = client.get("/api/pool/analyze")

    assert response.status_code == 404
    query = " ".join(cur.execute.call_args.args[0].split())
    assert "football_pool_issues" in query
    assert "model_prediction" not in query
    assert cur.fetchall.call_count == 1


def test_pool_analysis_uses_latest_complete_official_issue_for_historical_review(client):
    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    rows = [
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
        )
        for order in range(1, 15)
    ]
    newer = [(280, "26093", *row[2:12], row[12] + 1000) for row in rows]
    cur.fetchall.side_effect = [
        newer + rows,
        [(2000 + order, 0.45, 0.30, 0.25) for order in range(1, 9)],
        [(1000 + order, 0.45, 0.30, 0.25) for order in range(1, 15)],
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
    consensus_calls = [
        call for call in cur.execute.call_args_list if "latest_model_options" in call.args[0]
    ]
    assert [call.args[1]["match_ids"] for call in consensus_calls] == [
        list(range(2001, 2015)),
        list(range(1001, 1015)),
    ]


def test_closed_pool_never_backfills_a_recommendation_with_post_sale_predictions(client):
    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    rows = [
        (
            280,
            "26103",
            "t14c",
            14,
            "closed",
            "2026-08-11 22:00:00",
            order,
            None,
            f"主队{order}",
            f"客队{order}",
            "测试联赛",
            "2026-08-14 02:00:00",
            2000 + order,
        )
        for order in range(1, 15)
    ]
    cur.fetchall.side_effect = [rows, [(2000 + order, 0.45, 0.30, 0.25) for order in range(1, 9)]]

    with patch("apps.backend.src.routers.pool.get_db", return_value=conn):
        response = client.get("/api/pool/analyze?issue_id=26103")

    assert response.status_code == 409
    assert "已停售" in response.json()["detail"]
    assert "8/14" in response.json()["detail"]
    assert "不会使用停售后的数据追补推荐" in response.json()["detail"]


def test_current_pool_reads_only_its_matches_and_keeps_incomplete_state(client):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    conn.__enter__.return_value = conn
    current = [
        (
            280,
            "26103",
            "t14c",
            14,
            "selling",
            "2026-10-25 22:00",
            order,
            None,
            f"home{order}",
            f"away{order}",
            "league",
            "2026-10-26 02:00",
            2000 + order,
        )
        for order in range(1, 15)
    ]
    historical = [(279, "26102", *row[2:4], "closed", *row[5:]) for row in current]
    cur.fetchall.side_effect = [
        current + historical,
        [(2000 + order, 0.45, 0.30, 0.25) for order in range(1, 9)],
    ]
    with patch("apps.backend.src.routers.pool.get_db", return_value=conn):
        response = client.get("/api/pool/analyze")
    assert response.status_code == 409
    assert "8/14" in response.json()["detail"]
    consensus_calls = [
        call for call in cur.execute.call_args_list if "latest_model_options" in call.args[0]
    ]
    assert len(consensus_calls) == 1
    assert consensus_calls[0].args[1]["match_ids"] == list(range(2001, 2015))
