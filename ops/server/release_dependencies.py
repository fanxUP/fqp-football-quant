"""Classify the narrowly supported frontend dev dependency release changes."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

FRONTEND_MANIFEST = "apps/frontend/package.json"
FRONTEND_LOCK = "apps/frontend/package-lock.json"
ALLOWED_DIRECT_DEV_DEPENDENCIES = {"vite", "vitest"}


def _same_except_key(before: dict[str, Any], after: dict[str, Any], key: str) -> bool:
    before_without = {name: value for name, value in before.items() if name != key}
    after_without = {name: value for name, value in after.items() if name != key}
    return before_without == after_without


def _changed_keys(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    return {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}


def _is_direct_dev_dependency_update(
    old_manifest: dict[str, Any], new_manifest: dict[str, Any]
) -> bool:
    old_dev = old_manifest.get("devDependencies")
    new_dev = new_manifest.get("devDependencies")
    if not isinstance(old_dev, dict) or not isinstance(new_dev, dict):
        return False
    if old_dev.keys() != new_dev.keys():
        return False
    if not _same_except_key(old_manifest, new_manifest, "devDependencies"):
        return False
    changed = _changed_keys(old_dev, new_dev)
    return bool(changed) and changed <= ALLOWED_DIRECT_DEV_DEPENDENCIES


def _lock_package_is_dev(package: Any) -> bool:
    return isinstance(package, dict) and package.get("dev") is True


def _resolve_lock_package(
    package_path: str, dependency_name: str, packages: dict[str, Any]
) -> str | None:
    scope = package_path
    while scope:
        candidate = f"{scope}/node_modules/{dependency_name}"
        if candidate in packages:
            return candidate
        if "/node_modules/" in scope:
            scope = scope.rsplit("/node_modules/", 1)[0]
        elif scope.startswith("node_modules/"):
            scope = ""
        else:
            break
    root_candidate = f"node_modules/{dependency_name}"
    return root_candidate if root_candidate in packages else None


def _dev_dependency_closure(
    packages: dict[str, Any], direct_dependencies: set[str]
) -> set[str] | None:
    pending = {f"node_modules/{name}" for name in direct_dependencies}
    if any(path not in packages for path in pending):
        return None
    visited: set[str] = set()
    dependency_fields = ("dependencies", "optionalDependencies", "peerDependencies")
    while pending:
        package_path = pending.pop()
        if package_path in visited:
            continue
        package = packages.get(package_path)
        if not isinstance(package, dict):
            return None
        visited.add(package_path)
        for field in dependency_fields:
            dependencies = package.get(field, {})
            if not isinstance(dependencies, dict):
                return None
            for dependency_name in dependencies:
                resolved = _resolve_lock_package(package_path, dependency_name, packages)
                if resolved is not None:
                    pending.add(resolved)
    return visited


def frontend_dev_dependency_change_only(
    old_manifest: dict[str, Any],
    new_manifest: dict[str, Any],
    old_lock: dict[str, Any],
    new_lock: dict[str, Any],
) -> bool:
    """Return true only for Vite/Vitest direct and lockfile dev-only changes."""
    if not _is_direct_dev_dependency_update(old_manifest, new_manifest):
        return False
    if not _same_except_key(old_lock, new_lock, "packages"):
        return False

    old_packages = old_lock.get("packages")
    new_packages = new_lock.get("packages")
    if not isinstance(old_packages, dict) or not isinstance(new_packages, dict):
        return False

    old_root = old_packages.get("")
    new_root = new_packages.get("")
    if not isinstance(old_root, dict) or not isinstance(new_root, dict):
        return False
    if not _same_except_key(old_root, new_root, "devDependencies"):
        return False
    if old_root.get("devDependencies") != old_manifest["devDependencies"]:
        return False
    if new_root.get("devDependencies") != new_manifest["devDependencies"]:
        return False
    if old_root.get("dependencies", {}) != new_root.get("dependencies", {}):
        return False

    changed_direct_dependencies = _changed_keys(
        old_manifest["devDependencies"], new_manifest["devDependencies"]
    )
    old_closure = _dev_dependency_closure(old_packages, changed_direct_dependencies)
    new_closure = _dev_dependency_closure(new_packages, changed_direct_dependencies)
    if old_closure is None or new_closure is None:
        return False

    changed_packages = _changed_keys(old_packages, new_packages) - {""}
    if not changed_packages:
        return False
    if not changed_packages <= old_closure | new_closure:
        return False
    for package_name in changed_packages:
        old_package = old_packages.get(package_name)
        new_package = new_packages.get(package_name)
        if old_package == new_package:
            continue
        if old_package is not None and not _lock_package_is_dev(old_package):
            return False
        if new_package is not None and not _lock_package_is_dev(new_package):
            return False
    return True


def _read_json_at_revision(revision: str, path: str) -> dict[str, Any]:
    raw = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: release_dependencies.py <old-sha> <target-sha>", file=sys.stderr)
        return 2
    old_sha, new_sha = sys.argv[1:]
    try:
        allowed = frontend_dev_dependency_change_only(
            _read_json_at_revision(old_sha, FRONTEND_MANIFEST),
            _read_json_at_revision(new_sha, FRONTEND_MANIFEST),
            _read_json_at_revision(old_sha, FRONTEND_LOCK),
            _read_json_at_revision(new_sha, FRONTEND_LOCK),
        )
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        print(f"Could not classify frontend dependencies: {exc}", file=sys.stderr)
        return 1
    if not allowed:
        print(
            "Frontend changes are not limited to Vite/Vitest dev-only dependencies.",
            file=sys.stderr,
        )
        return 1
    print("Frontend dependency diff is limited to Vite/Vitest dev dependencies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
