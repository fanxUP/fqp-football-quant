"""Checks that the development API document stays aligned with OpenAPI."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from apps.backend.src.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def _documented_api_v1_routes() -> list[tuple[str, str]]:
    docs_text = (ROOT / "docs/06_API接口设计.md").read_text(encoding="utf-8")
    return re.findall(r"- (GET|POST|PUT|PATCH|DELETE) (/api/v1/[^\?\s]+)", docs_text)


def _normalize_path_params(path: str) -> str:
    return re.sub(r"\{[^/]+\}", "{}", path)


def test_documented_api_v1_paths_exist_in_openapi_contract() -> None:
    contract = yaml.safe_load((ROOT / "api/openapi.yaml").read_text(encoding="utf-8"))
    paths = contract["paths"]

    missing = [
        f"{method} {path}"
        for method, path in _documented_api_v1_routes()
        if path not in paths or method.lower() not in paths[path]
    ]

    assert missing == []


def test_documented_api_v1_paths_resolve_to_runtime_routes() -> None:
    app = create_app()
    runtime_routes: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods: set[str] = set(getattr(route, "methods", set()))
        if not path:
            continue
        for method in methods:
            runtime_routes.add((method, _normalize_path_params(path)))

    missing = []
    for method, path in _documented_api_v1_routes():
        runtime_path = "/api/" + path.removeprefix("/api/v1/")
        if (method, _normalize_path_params(runtime_path)) not in runtime_routes:
            missing.append(f"{method} {path}")

    assert missing == []
