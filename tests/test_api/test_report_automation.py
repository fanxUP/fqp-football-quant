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
        lambda _conn, _enabled: (_ for _ in ()).throw(ValueError("请先启用并测试自动赛后报告 Agent")),
    )

    response = client.put("/api/report-automation", json={"enabled": True})

    assert response.status_code == 422
    assert response.json()["detail"] == "请先启用并测试自动赛后报告 Agent"
