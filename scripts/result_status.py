"""Canonical helpers for official result terminal states."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

VOID_STATUSES = {"void", "voided", "refund", "refunded", "invalid", "cancelled", "canceled"}
VOID_TEXT_MARKERS = ("无效场次", "比赛取消", "取消比赛", "退款")


def _scalar_values(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for nested in value.values():
            yield from _scalar_values(nested)
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _scalar_values(nested)
    elif value is not None:
        yield str(value)


def is_void_official_result(raw_json: Any, result_status: Any = None) -> bool:
    """Return whether Sporttery marked a result invalid and refundable."""
    status = str(result_status or "").strip().lower()
    if status in VOID_STATUSES:
        return True

    for value in _scalar_values(raw_json):
        normalized = value.strip().lower()
        if normalized in VOID_STATUSES or any(marker in normalized for marker in VOID_TEXT_MARKERS):
            return True
    return False
