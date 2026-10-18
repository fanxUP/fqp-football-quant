"""Versioned metadata lookup, not runtime authorization or source enablement.

Purpose checking protects metadata consumers from accidental misuse only. A
caller-supplied purpose never authenticates a user or permits a database read.
Existing server authorization/release gates still apply to every actual read.
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from scripts.data_contracts import CONTRACT_VERSION, DataPurpose

_CATALOG_PATH = Path(__file__).resolve().parents[1] / "configs" / "data_catalog.yaml"


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    data = yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8"))
    if data["contract_version"] != CONTRACT_VERSION or data["runtime_authorization"] is not False:
        raise ValueError("unsupported data catalog contract")
    for source in data["sources"].values():
        if source["quota_owner"] != "P103":
            raise ValueError("sources must share the common quota owner")
    for product in data["products"].values():
        for purpose in product["purposes"]:
            DataPurpose(purpose)
    return data


def load_data_catalog() -> dict[str, Any]:
    """Return an isolated metadata copy, never runtime observations or credentials."""
    return deepcopy(_catalog())


def get_data_source(source_id: str) -> dict[str, Any]:
    return deepcopy(_catalog()["sources"][source_id])


def get_data_product(product_id: str, *, purpose: str) -> dict[str, Any]:
    requested = DataPurpose(purpose)
    product = _catalog()["products"][product_id]
    if requested.value not in product["purposes"]:
        raise PermissionError(f"data product {product_id} is not declared for {requested.value}")
    return deepcopy(product)
