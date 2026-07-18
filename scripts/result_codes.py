"""Normalization for official and legacy ticket result codes."""

from __future__ import annotations

from typing import Any


def normalize_result(play_type: str, value: Any) -> str | None:
    """Normalize official H/D/A-style values to canonical ticket codes."""
    if value is None:
        return None
    raw = str(value).strip()
    result_codes = {"H": "3", "h": "3", "D": "1", "d": "1", "A": "0", "a": "0"}
    if play_type in {"spf", "rqspf"}:
        return result_codes.get(raw, raw)
    if play_type == "bqc" and len(raw) == 2:
        return "".join(result_codes.get(ch, ch) for ch in raw)
    if play_type == "bqc":
        compact = raw.replace("/", "").replace("-", "").replace(" ", "")
        if len(compact) == 2:
            return "".join(result_codes.get(ch, ch) for ch in compact)
    if play_type == "bf":
        return raw.replace("-", ":").replace(" ", "")
    if play_type == "zjq" and raw in {"7+", "7plus", "7以上"}:
        return "7"
    return raw
