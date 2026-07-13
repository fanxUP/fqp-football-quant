"""Runtime module and UI panel registry endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["ui"])

ROOT = Path(__file__).resolve().parents[4]
MODULE_REGISTRY_PATH = ROOT / "configs" / "final_module_registry.yaml"
PANEL_REGISTRY_PATH = ROOT / "configs" / "final_panel_registry.yaml"
RUNTIME_STATE_PATH = ROOT / "data" / "runtime" / "module_state.json"
CATEGORY_ORDER = ["core_loop", "research", "strategy_lab", "maintenance"]
CATEGORY_MENU_GROUP = {
    "core_loop": "核心闭环",
    "research": "研究优化",
    "strategy_lab": "策略实验",
    "maintenance": "运维设置",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _load_modules() -> list[dict[str, Any]]:
    modules = _load_yaml(MODULE_REGISTRY_PATH).get("modules", [])
    return modules if isinstance(modules, list) else []


def _load_panels() -> list[dict[str, Any]]:
    panels = _load_yaml(PANEL_REGISTRY_PATH).get("panels", [])
    return panels if isinstance(panels, list) else []


def _load_runtime_state() -> dict[str, list[str]]:
    if not RUNTIME_STATE_PATH.exists():
        return {"disabledModules": []}
    data = json.loads(RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"disabledModules": []}
    disabled_modules = data.get("disabledModules", [])
    return {"disabledModules": disabled_modules if isinstance(disabled_modules, list) else []}


def _save_runtime_state(state: dict[str, list[str]]) -> None:
    RUNTIME_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _module_map() -> dict[str, dict[str, Any]]:
    modules = {}
    for module in _load_modules():
        payload = _module_payload(module)
        modules[payload["moduleCode"]] = payload
    return modules


def _module_payload(module: dict[str, Any], disabled_modules: set[str] | None = None) -> dict[str, Any]:
    module_code = str(module.get("module_id", ""))
    is_disabled = disabled_modules is not None and module_code in disabled_modules
    return {
        "moduleCode": module_code,
        "moduleName": str(module.get("name", module_code)),
        "category": str(module.get("category", "maintenance")),
        "required": bool(module.get("required", False)),
        "safeDisable": bool(module.get("safe_disable", False)),
        "status": "disabled" if is_disabled else str(module.get("status", "active")),
        "disabled": is_disabled,
        "dependsOn": list(module.get("depends_on", [])),
        "panels": list(module.get("panels", [])),
    }


def _enabled_dependents(module_code: str, modules: dict[str, dict[str, Any]], disabled_modules: set[str]) -> list[str]:
    return sorted(
        candidate_code
        for candidate_code, candidate in modules.items()
        if candidate_code not in disabled_modules and module_code in candidate["dependsOn"]
    )


@router.get("/api/modules")
def list_modules() -> dict[str, object]:
    """Return the final runtime module registry grouped by business layer."""

    disabled_modules = set(_load_runtime_state()["disabledModules"])
    modules = [_module_payload(module, disabled_modules) for module in _load_modules()]
    modules.sort(
        key=lambda item: (
            CATEGORY_ORDER.index(item["category"]) if item["category"] in CATEGORY_ORDER else 999,
            item["moduleCode"],
        )
    )
    categories = [
        category
        for category in CATEGORY_ORDER
        if any(module["category"] == category for module in modules)
    ]
    return {"modules": modules, "categories": categories, "total": len(modules)}


@router.patch("/api/modules/{module_code}/status")
def update_module_status(module_code: str, payload: dict[str, bool]) -> dict[str, object]:
    """Enable or disable a safe optional module in local runtime state."""

    modules = _module_map()
    if module_code not in modules:
        raise HTTPException(status_code=404, detail="module not found")

    disabled = bool(payload.get("disabled", False))
    state = _load_runtime_state()
    disabled_modules = set(state["disabledModules"])
    module = modules[module_code]

    if disabled:
        if module["required"]:
            raise HTTPException(status_code=409, detail="required module cannot be disabled")
        if not module["safeDisable"]:
            raise HTTPException(status_code=409, detail="module is not safe to disable")
        blocked_by = _enabled_dependents(module_code, modules, disabled_modules)
        if blocked_by:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "module has enabled dependents",
                    "blockedBy": blocked_by,
                },
            )
        disabled_modules.add(module_code)
    else:
        missing_dependencies = [
            dep for dep in module["dependsOn"] if dep in disabled_modules
        ]
        if missing_dependencies:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "module dependencies are disabled",
                    "missingDependencies": sorted(missing_dependencies),
                },
            )
        disabled_modules.discard(module_code)

    next_state = {"disabledModules": sorted(disabled_modules)}
    _save_runtime_state(next_state)
    updated = dict(module)
    updated["disabled"] = module_code in disabled_modules
    updated["status"] = "disabled" if updated["disabled"] else "active"
    return {"module": updated, "disabledModules": next_state["disabledModules"]}


@router.get("/api/ui/panels")
def list_ui_panels(
    disabled_modules: Annotated[list[str] | None, Query(alias="disabledModules")] = None,
) -> dict[str, object]:
    """Return visible UI panels from the final registry."""

    runtime_disabled = set(_load_runtime_state()["disabledModules"])
    modules = _module_map()
    safely_disabled = {
        module_code
        for module_code in runtime_disabled.union(disabled_modules or [])
        if module_code in modules and modules[module_code]["safeDisable"] and not modules[module_code]["required"]
    }

    panels: list[dict[str, object]] = []
    for panel in _load_panels():
        if not bool(panel.get("visible", True)):
            continue
        module_code = str(panel.get("module_id", ""))
        if module_code in safely_disabled:
            continue
        module = modules.get(module_code, {})
        category = str(module.get("category", "maintenance"))
        panel_code = str(panel.get("panel_id", ""))
        panels.append(
            {
                "panelCode": panel_code,
                "panelName": str(panel.get("name", panel_code)),
                "routePath": str(panel.get("route", "/")),
                "moduleCode": module_code,
                "moduleName": str(module.get("moduleName", module_code)),
                "category": category,
                "menuGroup": CATEGORY_MENU_GROUP.get(category, "运维设置"),
                "order": int(panel.get("order", 9999)),
                "visible": True,
                "icon": str(panel.get("icon", "")),
            }
        )

    panels.sort(key=lambda panel: (panel["order"], panel["panelCode"]))
    return {"panels": panels, "total": len(panels)}
