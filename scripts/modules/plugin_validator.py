"""FQP plugin manifest validator skeleton."""

from pathlib import Path

import yaml

REQUIRED = {"plugin_id", "name", "type", "module", "version", "status", "entrypoint"}
ALLOWED_STATUS = {
    "draft",
    "registered",
    "experimental",
    "staging",
    "active",
    "deprecated",
    "removed",
}


class PluginValidationError(Exception):
    pass


def validate_manifest(path: str) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    missing = REQUIRED - set(data.keys())
    if missing:
        raise PluginValidationError(f"missing fields: {sorted(missing)}")
    if data["status"] not in ALLOWED_STATUS:
        raise PluginValidationError(f"invalid status: {data['status']}")
    if data["status"] == "active" and not data.get("tests"):
        raise PluginValidationError("active plugin must define tests")
    if (
        data["type"] == "model"
        and data["status"] == "active"
        and not data.get("backtest_report_id")
    ):
        raise PluginValidationError("active model plugin must have backtest_report_id")
    return data


if __name__ == "__main__":
    import sys

    print(validate_manifest(sys.argv[1]))
