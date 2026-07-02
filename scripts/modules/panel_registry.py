"""FQP frontend panel registry skeleton.

The backend can expose this as /api/v1/ui/panels so the frontend menu is config-driven.
"""

from pathlib import Path

import yaml


class PanelRegistry:
    def __init__(self, panel_registry_path: str):
        self.path = Path(panel_registry_path)
        self.panels = []

    def load(self):
        self.panels = yaml.safe_load(self.path.read_text(encoding="utf-8")).get("panels", [])
        return self.panels

    def visible_panels(self, user_permissions: set[str], enabled_flags: set[str]):
        result = []
        for panel in self.panels:
            required = set(panel.get("permissions", []))
            flags = set(panel.get("feature_flags", []))
            if required and not required.issubset(user_permissions):
                continue
            if flags and not flags.issubset(enabled_flags):
                continue
            result.append(panel)
        return sorted(result, key=lambda p: (p.get("menu_group", ""), p.get("order", 9999)))


if __name__ == "__main__":
    registry = PanelRegistry("configs/panel_registry.yaml")
    registry.load()
    panels = registry.visible_panels(
        {"dashboard.view", "official_data.view.schedule"}, {"dashboard_enabled"}
    )
    print(panels)
