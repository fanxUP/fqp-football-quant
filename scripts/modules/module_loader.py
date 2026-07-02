"""FQP module loader skeleton.

Loads module registry, checks dependencies, exposes enabled modules to backend startup.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ModuleInfo:
    module_code: str
    module_name: str
    status: str
    version: str
    depends_on: list[str]


class ModuleLoader:
    def __init__(self, registry_path: str):
        self.registry_path = Path(registry_path)
        self.modules: dict[str, ModuleInfo] = {}

    def load(self) -> dict[str, ModuleInfo]:
        data = yaml.safe_load(self.registry_path.read_text(encoding="utf-8"))
        for item in data.get("modules", []):
            info = ModuleInfo(
                module_code=item["module_code"],
                module_name=item["module_name"],
                status=item.get("status", "disabled"),
                version=item.get("version", "0.0.0"),
                depends_on=item.get("depends_on", []),
            )
            self.modules[info.module_code] = info
        return self.modules

    def enabled_modules(self) -> list[ModuleInfo]:
        return [m for m in self.modules.values() if m.status == "active"]

    def validate_dependencies(self) -> list[str]:
        errors = []
        for module in self.enabled_modules():
            for dep in module.depends_on:
                if dep not in self.modules or self.modules[dep].status != "active":
                    errors.append(f"{module.module_code} depends on inactive/missing module {dep}")
        return errors


if __name__ == "__main__":
    loader = ModuleLoader("configs/module_registry.yaml")
    loader.load()
    errs = loader.validate_dependencies()
    if errs:
        raise SystemExit("\n".join(errs))
    print("enabled modules:", [m.module_code for m in loader.enabled_modules()])
