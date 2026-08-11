"""Read-only production gate for an explicitly approved news overlay."""

from __future__ import annotations

from typing import Any


def apply_overlay_rows(
    rows: list[tuple[Any, ...]],
    *,
    mode: str,
    overlays: dict[tuple[int, int], dict[str, float]],
) -> list[tuple[Any, ...]]:
    if mode != "production":
        return rows
    adjusted: list[tuple[Any, ...]] = []
    for row in rows:
        if len(row) < 18 or row[3] != "spf":
            adjusted.append(row)
            continue
        probabilities = overlays.get((int(row[1]), int(row[2])))
        option = str(row[4])
        if not probabilities or option not in probabilities:
            adjusted.append(row)
            continue
        values = list(row)
        probability = round(
            max(1e-9, min(1 - 1e-9, float(row[5]) + float(probabilities[option]))),
            9,
        )
        values[5] = probability
        sp_value = float(values[16] or 0)
        values[7] = round(probability * sp_value - 1, 6) if sp_value > 0 else None
        adjusted.append(tuple(values))
    return adjusted


def apply_approved_news_overlay(conn: Any, rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    if not rows:
        return rows
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT mode, approved_shadow_version
            FROM news_feature_release_settings
            WHERE id = 1
            """
        )
        setting = cur.fetchone()
        if not setting or setting[0] != "production" or not setting[1]:
            return rows
        match_ids = sorted({int(row[1]) for row in rows})
        model_version_ids = sorted({int(row[2]) for row in rows})
        cur.execute(
            """
            SELECT DISTINCT ON (match_id, baseline_model_version_id)
                   match_id, baseline_model_version_id,
                   baseline_probabilities, shadow_probabilities
            FROM news_shadow_predictions
            WHERE match_id = ANY(%s)
              AND baseline_model_version_id = ANY(%s)
              AND shadow_version = %s
            ORDER BY match_id, baseline_model_version_id, created_at DESC, id DESC
            """,
            (match_ids, model_version_ids, setting[1]),
        )
        overlays = {
            (int(row[0]), int(row[1])): {
                option: float(dict(row[3]).get(option, 0)) - float(dict(row[2]).get(option, 0))
                for option in ("3", "1", "0")
            }
            for row in cur.fetchall()
        }
    return apply_overlay_rows(rows, mode="production", overlays=overlays)
