"""Parsers for league season data (match results, standings, scorers)."""

from __future__ import annotations

import re
from typing import Any

from . import jsfmt


def _int(v: Any) -> int | None:
    try:
        return int(float(str(v).strip()))
    except TypeError, ValueError:
        return None


def _score(value: str):
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", str(value or "").strip())
    return (_int(m.group(1)), _int(m.group(2))) if m else (None, None)


def parse_sea_js(text: str) -> list[str]:
    return jsfmt.extract_js_literal(text, "arrSeason") or []


def parse_league_js(text: str) -> dict[str, Any]:
    arr_league = jsfmt.extract_js_literal(text, "arrLeague") or []
    arr_sub = jsfmt.extract_js_literal(text, "arrSubLeague") or []
    arr_team = jsfmt.extract_js_literal(text, "arrTeam") or []

    rounds: dict[int, list[Any]] = {}
    for m in re.finditer(r'jh\["R_(\d+)"\]\s*=\s*', text):
        start = m.end()
        if start >= len(text) or text[start] != "[":
            continue
        raw = jsfmt.extract_balanced_at(text, start)
        value = jsfmt.js_literal(raw)
        if isinstance(value, list):
            rounds[int(m.group(1))] = value

    def rows(name: str):
        value = jsfmt.extract_js_literal(text, name)
        return value if isinstance(value, list) else []

    last_m = re.search(r"var\s+lastUpdateTime\s*=\s*'([^']*)'", text)
    return {
        "league": arr_league,
        "sub_leagues": arr_sub,
        "teams": arr_team,
        "rounds": rounds,
        "standings": {
            "total": rows("totalScore"),
            "home": rows("homeScore"),
            "away": rows("guestScore"),
            "half_total": rows("halfScore"),
            "half_home": rows("homeHalfScore"),
            "half_away": rows("guestHalfScore"),
        },
        "score_colors": rows("scoreColor"),
        "last_update": last_m.group(1) if last_m else None,
    }


def parse_cup_js(text: str) -> dict[str, Any]:
    """解析杯赛 c{league_id}.js（arrCup + jh["G..."]/["S..."]）。"""
    groups: dict[str, list[Any]] = {}
    standings: dict[str, list[Any]] = {}
    for m in re.finditer(r'jh\["([GS])([A-Za-z0-9_]+)"\]\s*=\s*', text):
        start = m.end()
        if start >= len(text) or text[start] != "[":
            continue
        value = jsfmt.js_literal(jsfmt.extract_balanced_at(text, start))
        if not isinstance(value, list):
            continue
        key = f"{m.group(1)}{m.group(2)}"
        (groups if m.group(1) == "G" else standings)[key] = value

    last_m = re.search(r"var\s+lastUpdateTime\s*=\s*'([^']*)'", text)
    return {
        "league": jsfmt.extract_js_literal(text, "arrCup") or [],
        "kinds": jsfmt.extract_js_literal(text, "arrCupKind") or [],
        "teams": jsfmt.extract_js_literal(text, "arrTeam") or [],
        "groups": groups,
        "standings": standings,
        "last_update": last_m.group(1) if last_m else None,
    }


def _result_from_row(row: list[Any], round_no: int, season: str) -> dict[str, Any] | None:
    if not isinstance(row, list) or len(row) < 14:
        return None
    hs, aw = _score(row[6] if len(row) > 6 else "")
    hh, ah = _score(row[7] if len(row) > 7 else "")
    return {
        "match_id": _int(row[0]),
        "league_id": _int(row[1]),
        "season": season,
        "round": round_no,
        "status": _int(row[2]),
        "match_time": row[3],
        "home_id": _int(row[4]),
        "away_id": _int(row[5]),
        "home_score": hs,
        "away_score": aw,
        "home_half": hh,
        "away_half": ah,
        "home_rank": _int(row[8]),
        "away_rank": _int(row[9]),
        "ah_full": row[10],
        "ah_half": row[11],
        "ou_full": row[12],
        "ou_half": row[13],
        "flags": row[14:18],
        "home_red": _int(row[18]) if len(row) > 18 else None,
        "away_red": _int(row[19]) if len(row) > 19 else None,
        "note": row[20] if len(row) > 20 else None,
    }


def normalize_results(data: dict[str, Any], season: str) -> list[dict[str, Any]]:
    out = []
    for round_no, rows in sorted(data.get("rounds", {}).items()):
        for row in rows:
            rec = _result_from_row(row, round_no, season)
            if rec:
                out.append(rec)
    return out


def normalize_standings(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    layouts = {
        "total": ("total", 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16),
        "home": ("home", 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14),
        "away": ("away", 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14),
        "half_total": ("half", 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14),
        "half_home": ("half", 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14),
        "half_away": ("half", 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14),
    }
    for key, rows in data.get("standings", {}).items():
        if key not in layouts:
            continue
        period, ri, ti, pi, wi, di, li, gf, ga, gd, wr, dr, lr, agf, aga, pts = layouts[key]
        for row in rows:
            if not isinstance(row, list) or len(row) <= pts:
                continue
            out.append(
                {
                    "scope": key,
                    "period": period,
                    "rank": _int(row[ri]),
                    "team_id": _int(row[ti]),
                    "played": _int(row[pi]),
                    "win": _int(row[wi]),
                    "draw": _int(row[di]),
                    "loss": _int(row[li]),
                    "goals_for": _int(row[gf]),
                    "goals_against": _int(row[ga]),
                    "goal_diff": _int(row[gd]),
                    "win_rate": row[wr],
                    "draw_rate": row[dr],
                    "loss_rate": row[lr],
                    "goals_for_avg": row[agf],
                    "goals_against_avg": row[aga],
                    "points": _int(row[pts]),
                }
            )
    return out


def _iter_cup_match_rows(value: Any, league_id: int):
    """杯赛 G 数组里嵌套了分组/两回合结构，递归取出比赛行。"""
    if not isinstance(value, list):
        return
    if (
        len(value) >= 14
        and isinstance(value[0], int)
        and isinstance(value[1], int)
        and value[1] == league_id
    ):
        yield value
        return
    for item in value:
        yield from _iter_cup_match_rows(item, league_id)


def normalize_cup_results(
    data: dict[str, Any], season: str, league_id: int
) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for key, value in data.get("groups", {}).items():
        m = re.match(r"G(\d+)", key)
        round_no = _int(m.group(1)) if m else None
        for row in _iter_cup_match_rows(value, league_id):
            if row[0] in seen:
                continue
            rec = _result_from_row(row, round_no, season)
            if rec:
                seen.add(row[0])
                out.append(rec)
    return out


def normalize_cup_standings(data: dict[str, Any]) -> list[dict[str, Any]]:
    """杯赛积分榜行：[排名,球队,赛,胜,平,负,得,失,净,积分,...]。"""
    out = []
    for key, rows in data.get("standings", {}).items():
        for row in rows:
            if not isinstance(row, list) or len(row) < 10:
                continue
            out.append(
                {
                    "scope": key,
                    "period": "total",
                    "rank": _int(row[0]),
                    "team_id": _int(row[1]),
                    "played": _int(row[2]),
                    "win": _int(row[3]),
                    "draw": _int(row[4]),
                    "loss": _int(row[5]),
                    "goals_for": _int(row[6]),
                    "goals_against": _int(row[7]),
                    "goal_diff": _int(row[8]),
                    "win_rate": None,
                    "draw_rate": None,
                    "loss_rate": None,
                    "goals_for_avg": None,
                    "goals_against_avg": None,
                    "points": _int(row[9]),
                }
            )
    return out


def cup_league_info(data: dict[str, Any]) -> list[Any]:
    """把 arrCup 映射成 save_league 期望的 arrLeague 布局。"""
    cup = data.get("league") or []
    if len(cup) < 4:
        return []

    def at(i):
        return cup[i] if len(cup) > i else None

    return [
        at(0),
        at(1),
        at(2),
        at(3),
        at(4),
        at(9),
        at(8),
        at(4),
        at(5),
        at(10),
    ]


def parse_scorers(html: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for key, name in (("total", "arrTotalData"), ("home", "arrHomeData"), ("away", "arrGuestData")):
        rows = jsfmt.extract_js_literal(html, name) or []
        normalized = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 13:
                continue
            normalized.append(
                {
                    "scope": key,
                    "rank": _int(row[0]),
                    "player_id": _int(row[1]),
                    "name": row[2],
                    "name_traditional": row[3],
                    "name_en": row[4],
                    "nationality": row[5],
                    "nationality_traditional": row[6],
                    "nationality_en": row[7],
                    "team_id": _int(row[8]),
                    "goals": _int(row[9]),
                    "home_goals": _int(row[10]),
                    "away_goals": _int(row[11]),
                    "penalties": _int(row[12]),
                    "extra": row[13:],
                }
            )
        out[key] = normalized
    return out


def parse_player_tech_scorers(text: str) -> list[dict[str, Any]]:
    """解析 jsData/Count/{season}/playerTech_{league}.js 的射手数据。"""
    obj = jsfmt.extract_js_literal(text, "techCout_Player")
    if not isinstance(obj, dict):
        return []
    total = (obj.get("Total") or {}).get("value") or []
    pid_map = obj.get("Pid") or {}
    rows = []
    for value in total:
        if not isinstance(value, list) or len(value) < 53:
            continue
        pid = _int(value[0])
        if not pid:
            continue
        names = (pid_map.get(str(pid)) or [[]])[0]
        rows.append(
            {
                "scope": "total",
                "rank": None,
                "player_id": pid,
                "name": names[0] if len(names) > 0 else None,
                "name_traditional": names[1] if len(names) > 1 else None,
                "name_en": names[2] if len(names) > 2 else None,
                "nationality": None,
                "nationality_traditional": None,
                "nationality_en": None,
                "team_id": None,
                "goals": _int(value[52]),
                "home_goals": None,
                "away_goals": None,
                "penalties": _int(value[5]),
                "extra": {
                    "appearances": value[1],
                    "assist": value[15],
                    "yellow": value[34],
                    "red": value[33],
                },
            }
        )
    rows.sort(key=lambda r: r.get("goals") or 0, reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def find_player_tech_url(html: str) -> str | None:
    m = re.search(r"""src=["']([^"']*jsData/Count/[^"']*playerTech[^"']*\.js)""", html)
    return m.group(1) if m else None


def parse_best_team(html: str) -> list[Any]:
    return jsfmt.extract_js_literal(html, "arrBestPlayers") or []


def parse_season_from_title(html: str) -> str | None:
    m = re.search(r"(\d{4}(?:-\d{4})?)赛季", html)
    return m.group(1) if m else None


def parse_sub_league_id(html: str) -> int | None:
    m = re.search(r"SubSclassID\s*=\s*(\d+)", html)
    if not m:
        return None
    value = _int(m.group(1))
    return value or None
