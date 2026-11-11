"""Parser for info.titan007.com team data bundles (tdl{teamId}.js)."""

from __future__ import annotations

from typing import Any

from . import jsfmt


def _int(v: Any) -> int | None:
    try:
        return int(float(str(v).strip()))
    except TypeError, ValueError:
        return None


def _split_names(value: Any) -> list[str]:
    return str(value or "").split("^")


def parse_team_js(text: str) -> dict[str, Any]:
    names = [
        "teamDetail",
        "goalkeeper",
        "rearguard",
        "midfielder",
        "vanguard",
        "coach",
        "lineupDetail",
        "leagueData",
        "cupData",
        "countSum",
        "teamCount",
        "teamHonor",
        "teamCharacter",
        "teamLastUpdateTime",
    ]
    return {name: jsfmt.extract_js_literal(text, name) for name in names}


def normalize_team(data: dict[str, Any]) -> dict[str, Any]:
    detail = data.get("teamDetail") or []
    profile = {}
    if len(detail) >= 14:
        profile = {
            "team_id": _int(detail[0]),
            "name": detail[1],
            "name_traditional": detail[2],
            "name_en": detail[3],
            "logo": detail[4],
            "city": detail[5],
            "city_traditional": detail[6],
            "city_en": detail[7],
            "stadium": detail[8],
            "stadium_traditional": detail[9],
            "stadium_en": detail[10],
            "capacity": _int(detail[11]),
            "founded": detail[12],
            "website": detail[13],
            "description": detail[14] if len(detail) > 14 else None,
            "address": detail[15] if len(detail) > 15 else None,
        }

    details = {str(r[0]): r for r in (data.get("lineupDetail") or []) if r}
    details_by_name = {
        str(r[2]).strip(): r for r in (data.get("lineupDetail") or []) if r and len(r) > 2
    }
    squad = []
    groups = (
        ("goalkeeper", "门将"),
        ("rearguard", "后卫"),
        ("midfielder", "中场"),
        ("vanguard", "前锋"),
        ("coach", "教练"),
    )
    for key, group_name in groups:
        for row in data.get(key) or []:
            if len(row) < 5:
                continue
            pid = str(row[0])
            d = details.get(pid) or details_by_name.get(str(row[2]).strip()) or []
            squad.append(
                {
                    "team_id": profile.get("team_id"),
                    "player_id": _int(row[0]),
                    "number": str(row[1]).strip() if row[1] is not None else None,
                    "name": row[2],
                    "name_traditional": row[3],
                    "name_en": row[4],
                    "group": group_name,
                    "birth": d[5] if len(d) > 5 else None,
                    "height": d[6] if len(d) > 6 else None,
                    "weight": d[7] if len(d) > 7 else None,
                    "position": d[8] if len(d) > 8 else None,
                    "nationality": d[9] if len(d) > 9 else None,
                    "nationality_traditional": d[10] if len(d) > 10 else None,
                    "contract_end": d[12] if len(d) > 12 else None,
                    "appearances": _int(d[13]) if len(d) > 13 else None,
                    "goals": _int(d[14]) if len(d) > 14 else None,
                    "extra_json": d[15:] if len(d) > 15 else [],
                }
            )

    league_stats = []
    scopes = ["主", "客", "总", "半场-主", "半场-客", "半场-总"]
    for i, row in enumerate(data.get("leagueData") or []):
        if not isinstance(row, list) or len(row) < 13:
            continue
        league_stats.append(
            {
                "team_id": profile.get("team_id"),
                "scope": scopes[i] if i < len(scopes) else f"row{i}",
                "played": _int(row[0]),
                "win": _int(row[1]),
                "draw": _int(row[2]),
                "loss": _int(row[3]),
                "goals_for": _int(row[4]),
                "goals_against": _int(row[5]),
                "goal_diff": _int(row[6]),
                "win_rate": row[7],
                "draw_rate": row[8],
                "loss_rate": row[9],
                "goals_for_avg": row[10],
                "goals_against_avg": row[11],
                "points": _int(row[12]),
            }
        )

    honors = []
    for row in data.get("teamHonor") or []:
        if len(row) >= 3:
            names = _split_names(row[0])
            honors.append(
                {
                    "team_id": profile.get("team_id"),
                    "competition": names[0],
                    "competition_traditional": names[1] if len(names) > 1 else None,
                    "years": row[1],
                    "competition_id": _int(row[2]),
                }
            )

    cups = []
    for row in data.get("cupData") or []:
        if len(row) >= 4:
            names = _split_names(row[1])
            cups.append(
                {
                    "team_id": profile.get("team_id"),
                    "league_id": _int(row[0]),
                    "name": names[0],
                    "name_traditional": names[1] if len(names) > 1 else None,
                    "season": row[3],
                }
            )

    return {
        "profile": profile,
        "squad": squad,
        "league_stats": league_stats,
        "honors": honors,
        "cups": cups,
        "matches": data.get("teamCount") or [],
        "count_sum": data.get("countSum") or [],
        "characters": data.get("teamCharacter") or [],
    }
