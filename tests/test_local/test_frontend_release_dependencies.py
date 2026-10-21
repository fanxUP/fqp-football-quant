from copy import deepcopy
from pathlib import Path

from ops.server.release_dependencies import frontend_dev_dependency_change_only


def fixtures() -> tuple[dict, dict, dict, dict]:
    old_manifest = {
        "name": "frontend",
        "scripts": {"build": "vite build"},
        "dependencies": {"react": "19.2.7"},
        "devDependencies": {"vite": "8.1.2", "vitest": "^4.1.9", "typescript": "^6.0.3"},
    }
    new_manifest = deepcopy(old_manifest)
    new_manifest["devDependencies"]["vite"] = "8.1.6"
    new_manifest["devDependencies"]["vitest"] = "^4.1.12"
    old_lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {
                "name": "frontend",
                "scripts": {"build": "vite build"},
                "dependencies": {"react": "19.2.7"},
                "devDependencies": old_manifest["devDependencies"],
            },
            "node_modules/vite": {"version": "8.1.2", "dev": True},
            "node_modules/vitest": {
                "version": "4.1.9",
                "dev": True,
                "dependencies": {"@vitest/mocker": "4.1.9"},
            },
            "node_modules/@vitest/mocker": {"version": "4.1.9", "dev": True},
        },
    }
    new_lock = deepcopy(old_lock)
    new_lock["packages"][""]["devDependencies"] = new_manifest["devDependencies"]
    new_lock["packages"]["node_modules/vite"]["version"] = "8.1.6"
    new_lock["packages"]["node_modules/vitest"]["version"] = "4.1.12"
    new_lock["packages"]["node_modules/vitest"]["dependencies"] = {"@vitest/mocker": "4.1.12"}
    new_lock["packages"]["node_modules/@vitest/mocker"]["version"] = "4.1.12"
    return old_manifest, new_manifest, old_lock, new_lock


def test_allows_only_vite_vitest_dev_dependency_updates() -> None:
    old_manifest, new_manifest, old_lock, new_lock = fixtures()

    assert frontend_dev_dependency_change_only(old_manifest, new_manifest, old_lock, new_lock)


def test_rejects_frontend_production_dependency_changes() -> None:
    old_manifest, new_manifest, old_lock, new_lock = fixtures()
    new_manifest["dependencies"]["react"] = "19.3.0"
    new_lock["packages"][""]["dependencies"]["react"] = "19.3.0"

    assert not frontend_dev_dependency_change_only(old_manifest, new_manifest, old_lock, new_lock)


def test_rejects_other_dev_dependency_changes() -> None:
    old_manifest, new_manifest, old_lock, new_lock = fixtures()
    new_manifest["devDependencies"]["typescript"] = "^6.1.0"
    new_lock["packages"][""]["devDependencies"] = new_manifest["devDependencies"]

    assert not frontend_dev_dependency_change_only(old_manifest, new_manifest, old_lock, new_lock)


def test_rejects_changed_lock_entries_without_dev_only_markers() -> None:
    old_manifest, new_manifest, old_lock, new_lock = fixtures()
    new_lock["packages"]["node_modules/@vitest/mocker"]["dev"] = False

    assert not frontend_dev_dependency_change_only(old_manifest, new_manifest, old_lock, new_lock)


def test_rejects_unrelated_dev_only_lock_entry_changes() -> None:
    old_manifest, new_manifest, old_lock, new_lock = fixtures()
    old_lock["packages"]["node_modules/left-pad"] = {"version": "1.3.0", "dev": True}
    new_lock["packages"]["node_modules/left-pad"] = {"version": "1.3.1", "dev": True}

    assert not frontend_dev_dependency_change_only(old_manifest, new_manifest, old_lock, new_lock)


def test_release_runner_loads_classifier_from_its_staged_directory() -> None:
    project_root = Path(__file__).resolve().parents[2]
    runner = (project_root / "ops/server/deploy.sh").read_text(encoding="utf-8")

    assert '.venv/bin/python "$SCRIPT_DIR/release_dependencies.py"' in runner
