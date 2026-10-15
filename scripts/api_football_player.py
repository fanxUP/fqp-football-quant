"""Shared player lookup and field mapping for API-Football collectors."""

from __future__ import annotations

from typing import Any

from scripts.feature_storage import get_player_by_code, store_player


def _safe_height(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(" cm", "").strip())
    except ValueError:
        return None


def get_or_create_player(
    conn: Any,
    player_data: dict[str, Any],
    *,
    prefer_short_position: bool,
) -> int | None:
    player_code = f"apifootball:{player_data.get('id')}"
    existing = get_player_by_code(conn, player_code)
    if existing:
        return int(existing["id"])
    return store_player(
        conn,
        {
            "player_code": player_code,
            "player_name_en": player_data.get("name", ""),
            "player_name_cn": "",
            "birth_date": (
                player_data.get("birth", {}).get("date")
                if isinstance(player_data.get("birth"), dict)
                else None
            ),
            "nationality": player_data.get("nationality", ""),
            "primary_position": (
                player_data.get("pos") or player_data.get("position", "")
                if prefer_short_position
                else player_data.get("position", "")
            ),
            "secondary_positions": [],
            "preferred_foot": "",
            "height_cm": _safe_height(player_data.get("height")),
        },
    )
