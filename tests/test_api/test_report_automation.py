from apps.backend.src.routers import report_automation


def test_report_automation_state_is_available_as_a_stable_resource(client, monkeypatch) -> None:
    state = {
        "enabled": False,
        "agentCode": "post_match_report_agent",
        "agentReady": False,
        "providerName": None,
        "model": None,
    }
    monkeypatch.setattr(report_automation, "get_post_match_report_automation", lambda _conn: state)

    response = client.get("/api/report-automation")

    assert response.status_code == 200
    assert response.json() == {"automation": state}


def test_report_automation_update_requires_a_ready_agent(client, monkeypatch) -> None:
    monkeypatch.setattr(
        report_automation,
        "set_post_match_report_automation",
        lambda _conn, _enabled: (_ for _ in ()).throw(
            ValueError("请先启用并测试自动赛后报告 Agent")
        ),
    )

    response = client.put("/api/report-automation", json={"enabled": True})

    assert response.status_code == 422
    assert response.json()["detail"] == "请先启用并测试自动赛后报告 Agent"


def test_report_automation_archive_exposes_only_the_matching_automatic_report(
    client, monkeypatch
) -> None:
    task = {
        "id": 21,
        "sourceType": "post_weekly",
        "sourceRef": "2026-08-03",
        "response": "仅供人工核验",
    }
    monkeypatch.setattr(
        report_automation, "get_workspace_task_for_source", lambda _conn, **_kwargs: task
    )

    response = client.get("/api/report-automation/archive/post_weekly/2026-08-03")

    assert response.status_code == 200
    assert response.json() == {"task": task}


def test_report_automation_archive_rejects_unknown_business_source(client) -> None:
    response = client.get("/api/report-automation/archive/other/2026-08-03")

    assert response.status_code == 422


def test_report_automation_snapshot_exposes_only_safe_frozen_report_metrics(
    client, monkeypatch
) -> None:
    report = {
        "sourceType": "post_daily",
        "sourceRef": "2026-08-09",
        "schemaVersion": 2,
        "researchMetrics": {"matchCount": 3, "averageEdge": 0.06},
        "dailyReview": {"actualStake": 100, "realProfitLoss": 20},
    }
    monkeypatch.setattr(
        report_automation, "get_report_snapshot_for_source", lambda _conn, **_kwargs: report
    )

    response = client.get("/api/report-automation/snapshot/post_daily/2026-08-09")

    assert response.status_code == 200
    assert response.json() == {"report": report}
