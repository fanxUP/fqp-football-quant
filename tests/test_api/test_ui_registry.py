"""Runtime module and panel registry API tests."""

from __future__ import annotations

from pathlib import Path

from apps.backend.src.routers import ui


def _use_runtime_state(tmp_path, monkeypatch) -> Path:
    state_path = tmp_path / "module_state.json"
    monkeypatch.setattr(ui, "RUNTIME_STATE_PATH", state_path)
    return state_path


def test_modules_endpoint_reads_final_registry(client, tmp_path, monkeypatch):
    _use_runtime_state(tmp_path, monkeypatch)

    resp = client.get("/api/v1/modules")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 12
    modules = {module["moduleCode"]: module for module in data["modules"]}
    assert modules["official_data_core"] == {
        "moduleCode": "official_data_core",
        "moduleName": "官方数据核心",
        "category": "core_loop",
        "required": True,
        "safeDisable": False,
        "status": "active",
        "disabled": False,
        "dependsOn": [],
        "panels": ["today_dashboard", "match_center", "event_center", "odds_movement"],
    }
    assert data["categories"] == ["core_loop", "research", "strategy_lab", "maintenance"]


def test_ui_panels_endpoint_reads_final_registry_in_order(client, tmp_path, monkeypatch):
    _use_runtime_state(tmp_path, monkeypatch)

    resp = client.get("/api/v1/ui/panels")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 16
    assert [panel["panelName"] for panel in data["panels"]] == [
        "今日驾驶舱",
        "比赛中心",
        "赛事中心",
        "赔率走势",
        "投注中心",
        "今日决策分析",
        "特征数据健康",
        "模型表现",
        "模型接入",
        "冷门研究",
        "策略验证",
        "足彩彩池",
        "系统监控",
        "功能模块",
        "系统设置",
        "智能代理",
    ]
    assert data["panels"][0] == {
        "panelCode": "today_dashboard",
        "panelName": "今日驾驶舱",
        "routePath": "/",
        "moduleCode": "official_data_core",
        "moduleName": "官方数据核心",
        "category": "core_loop",
        "menuGroup": "核心闭环",
        "order": 10,
        "visible": True,
        "icon": "chart",
    }
    data_health = next(panel for panel in data["panels"] if panel["panelCode"] == "data_health")
    assert data_health["menuGroup"] == "运维设置"


def test_ui_panels_endpoint_filters_only_safely_disabled_modules(client, tmp_path, monkeypatch):
    _use_runtime_state(tmp_path, monkeypatch)

    resp = client.get(
        "/api/v1/ui/panels",
        params=[
            ("disabledModules", "pool_lottery_module"),
            ("disabledModules", "official_data_core"),
        ],
    )

    assert resp.status_code == 200
    names = [panel["panelName"] for panel in resp.json()["panels"]]
    assert "足彩彩池" not in names
    assert "今日驾驶舱" in names
    assert "比赛中心" in names


def test_module_status_patch_persists_runtime_disabled_state(client, tmp_path, monkeypatch):
    state_path = _use_runtime_state(tmp_path, monkeypatch)

    resp = client.patch("/api/v1/modules/pool_lottery_module/status", json={"disabled": True})

    assert resp.status_code == 200
    assert resp.json()["module"]["disabled"] is True
    assert state_path.exists()

    panels_resp = client.get("/api/v1/ui/panels")
    names = [panel["panelName"] for panel in panels_resp.json()["panels"]]
    assert "足彩彩池" not in names

    modules_resp = client.get("/api/v1/modules")
    modules = {module["moduleCode"]: module for module in modules_resp.json()["modules"]}
    assert modules["pool_lottery_module"]["status"] == "disabled"


def test_module_status_patch_rejects_required_modules(client, tmp_path, monkeypatch):
    _use_runtime_state(tmp_path, monkeypatch)

    resp = client.patch("/api/v1/modules/official_data_core/status", json={"disabled": True})

    assert resp.status_code == 409
    assert resp.json()["detail"] == "required module cannot be disabled"


def test_module_status_patch_rejects_enabled_dependents(client, tmp_path, monkeypatch):
    _use_runtime_state(tmp_path, monkeypatch)

    resp = client.patch("/api/v1/modules/multidim_feature_module/status", json={"disabled": True})

    assert resp.status_code == 409
    assert resp.json()["detail"]["blockedBy"] == ["model_research_module"]
