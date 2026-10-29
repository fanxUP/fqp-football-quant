"""Parser for zq.titan007.com analysis pages."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from . import jsfmt


def _clean(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _strip_html(s: Any) -> str:
    if not s:
        return ""
    return _clean(BeautifulSoup(str(s), "html.parser").get_text(" ", strip=True))


def _int(v: Any) -> int | None:
    match = re.search(r"-?\d+", str(v))
    return int(match.group()) if match else None


def _team_link(row) -> tuple:
    a = row.find("a", href=True) if row else None
    if not a:
        return None, None
    m = re.search(r"/team/Summary/(\d+)", a["href"])
    return (_int(m.group(1)) if m else None), _clean(a.get_text(" ", strip=True))


def _norm_history(row: list[Any]) -> dict[str, Any]:
    def at(i, default=None):
        return row[i] if i < len(row) else default

    return {
        "date": at(0),
        "league_id": at(1),
        "league_name": at(2),
        "league_color": at(3),
        "home_id": at(4),
        "home_name": _strip_html(at(5)),
        "away_id": at(6),
        "away_name": _strip_html(at(7)),
        "home_score": at(8),
        "away_score": at(9),
        "half_score": at(10),
        "handicap": at(11),
        "match_id": at(15),
        "home_rank": at(16),
        "away_rank": at(17),
        "league_url": at(18),
        "extra": row[19:],
    }


def parse_standings(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    container = soup.find(id="porlet_5")
    if not container:
        return out
    full_tables = []
    half_tables = []
    for table in container.find_all("table"):
        rows = table.find_all("tr", recursive=False)
        if len(rows) < 3:
            continue
        header_text = _clean(rows[0].get_text(" ", strip=True))
        m = re.search(r"\[(.*?)-(\d+)\]\s*(.+)", header_text)
        if m:
            team_id, _ = _team_link(rows[0])
            full_tables.append(
                (team_id, _clean(m.group(3)), _clean(m.group(1)), _int(m.group(2)), rows)
            )
        elif header_text.startswith("半场"):
            half_tables.append(rows)

    def add_rows(rows, team_id, team_name, league_name, league_rank, period):
        for row in rows:
            cells = [_clean(td.get_text(" ", strip=True)) for td in row.find_all("td")]
            if len(cells) < 11 or cells[0] not in ("总", "主", "客", "近6"):
                continue
            out.append(
                {
                    "team_id": team_id,
                    "team_name": team_name,
                    "league_name": league_name,
                    "league_rank": league_rank,
                    "period": period,
                    "scope": cells[0],
                    "played": _int(cells[1]),
                    "win": _int(cells[2]),
                    "draw": _int(cells[3]),
                    "loss": _int(cells[4]),
                    "goals_for": _int(cells[5]),
                    "goals_against": _int(cells[6]),
                    "goal_diff": _int(cells[7]),
                    "points": _int(cells[8]),
                    "rank": _int(cells[9]),
                    "win_rate": cells[10],
                }
            )

    for team_id, team_name, league_name, league_rank, rows in full_tables:
        add_rows(rows[1:], team_id, team_name, league_name, league_rank, "全场")
    for idx, rows in enumerate(half_tables):
        if not full_tables:
            continue
        team_id, team_name, league_name, league_rank, _ = full_tables[idx % len(full_tables)]
        add_rows(rows, team_id, team_name, league_name, league_rank, "半场")
    return out


def _find_container(soup: BeautifulSoup, text: str):
    node = soup.find(string=lambda t: t and text in t)
    if not node:
        return None
    return node.find_parent("div", class_="porletP") or node.parent


def parse_team_tables(
    soup: BeautifulSoup, title: str, expected_header: str
) -> list[dict[str, Any]]:
    container = _find_container(soup, title)
    if not container:
        return []
    out = []
    for table in container.find_all("table"):
        rows = table.find_all("tr", recursive=False)
        if len(rows) < 3:
            continue
        header = _clean(rows[1].get_text(" ", strip=True)) if len(rows) > 1 else ""
        if expected_header not in header:
            continue
        team_id, team_name = _team_link(rows[0])
        for row in rows[2:]:
            cells = [_clean(td.get_text(" ", strip=True)) for td in row.find_all("td")]
            if not any(cells):
                continue
            out.append({"team_id": team_id, "team_name": team_name, "cells": cells})
    return out


def parse_injuries(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out = []
    for item in parse_team_tables(soup, "阵容情况", "缺阵原因"):
        if len(item["cells"]) < 2:
            continue
        player = item["cells"][0]
        m = re.match(r"(\d+)\s*\(([^)]+)\)\s*(.+)", player)
        out.append(
            {
                "team_id": item["team_id"],
                "team_name": item["team_name"],
                "number": _int(m.group(1)) if m else None,
                "position": m.group(2) if m else None,
                "player_name": _clean(m.group(3)) if m else player,
                "reason": item["cells"][1],
            }
        )
    return out


def parse_ratings(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out = []
    for item in parse_team_tables(soup, "球员上一场出场评分", "评分"):
        cells = item["cells"]
        if len(cells) < 5:
            continue
        out.append(
            {
                "team_id": item["team_id"],
                "team_name": item["team_name"],
                "number": _int(cells[0]),
                "player_name": cells[1],
                "position": cells[2],
                "starter": 1 if cells[3] == "*" else 0,
                "rating": cells[4],
            }
        )
    return out


def parse_next_matches(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out = []
    for item in parse_team_tables(soup, "未来五场", "相隔"):
        cells = item["cells"]
        if len(cells) < 5:
            continue
        out.append(
            {
                "team_id": item["team_id"],
                "team_name": item["team_name"],
                "date": cells[0],
                "league_name": cells[1],
                "fixture": cells[2],
                "days": cells[-1],
            }
        )
    return out


def parse_sections_text(soup: BeautifulSoup) -> dict[str, str]:
    sections: dict[str, str] = {}
    for h2 in soup.find_all("h2", class_="fx_title2"):
        title = _clean(h2.get_text(" ", strip=True))
        if not title:
            continue
        container = h2.find_parent("div", class_="porletP")
        if not container:
            continue
        text = _clean(container.get_text("\n", strip=True))
        if text.startswith(title):
            text = text[len(title) :].strip()
        sections[title] = text[:50000]
    return sections


def _filter_odds_rows(rows: Any) -> list[Any]:
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, list):
            continue
        values = [str(x).strip() for x in row[1:8]]
        if any(v not in ("", "None", "nan") for v in values):
            out.append(row)
    return out


def parse_zq_analysis(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Any] = {"meta": {}, "sections": {}}

    def js_str(name: str) -> str | None:
        m = re.search(rf'var\s+{name}\s*=\s*"([^"]*)"', html) or re.search(
            rf"var\s+{name}\s*=\s*'([^']*)'", html
        )
        return m.group(1) if m else None

    def js_int(name: str) -> int | None:
        m = re.search(rf"var\s+{name}\s*=\s*(-?\d+)", html)
        return _int(m.group(1)) if m else None

    meta = out["meta"]
    meta.update(
        {
            "match_id": js_int("scheduleID"),
            "home_id": js_int("h2h_home"),
            "away_id": js_int("h2h_away"),
            "home_name": js_str("hometeam"),
            "away_name": js_str("guestteam"),
            "kickoff": js_str("strTime"),
        }
    )
    lname = soup.select_one("a.LName")
    if lname:
        meta["league_round"] = _clean(lname.get_text(" ", strip=True))
        parent = lname.parent
        if parent:
            parent_text = _clean(parent.get_text(" ", strip=True))
            m = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", parent_text)
            if m:
                meta["match_date"], meta["kickoff_time"] = m.group(1), m.group(2)
    place = soup.select_one("a.place")
    if place:
        meta["venue"] = _clean(place.get_text(" ", strip=True)).replace("场地：", "").strip()
    for text_node in soup.find_all(string=re.compile("天气：")):
        weather_text = _clean(text_node)
        meta["weather_text"] = weather_text
        m = re.search(r"天气：\s*([^\s]+)", weather_text)
        if m:
            meta["weather"] = m.group(1)
        m = re.search(r"温度：\s*([^\s]+)", weather_text)
        if m:
            meta["temperature"] = m.group(1)
        break

    out["h2h"] = [_norm_history(r) for r in (jsfmt.extract_js_literal(html, "v_data") or [])]
    out["form_home"] = [_norm_history(r) for r in (jsfmt.extract_js_literal(html, "h_data") or [])]
    out["form_away"] = [_norm_history(r) for r in (jsfmt.extract_js_literal(html, "a_data") or [])]
    out["form_home_same"] = [
        _norm_history(r) for r in (jsfmt.extract_js_literal(html, "h2_data") or [])
    ]
    out["form_away_same"] = [
        _norm_history(r) for r in (jsfmt.extract_js_literal(html, "a2_data") or [])
    ]
    out["odds_compare_asian"] = _filter_odds_rows(jsfmt.extract_js_literal(html, "Vs_hOdds") or [])
    out["odds_compare_europe"] = _filter_odds_rows(jsfmt.extract_js_literal(html, "Vs_eOdds") or [])

    out["standings"] = parse_standings(soup)
    out["injuries"] = parse_injuries(soup)
    out["ratings"] = parse_ratings(soup)
    out["next_matches"] = parse_next_matches(soup)
    out["sections"] = parse_sections_text(soup)

    briefing_h2 = soup.find(
        lambda tag: tag.name == "h2" and "赛前简报" in tag.get_text(" ", strip=True)
    )
    if briefing_h2:
        container = briefing_h2.find_parent("div", class_="porletP") or briefing_h2.parent
        if container:
            text = _clean(container.get_text("\n", strip=True))
            out["briefing"] = text.replace("赛前简报", "", 1).strip()

    cup = soup.find(id="cupScore")
    if cup:
        cup_text = _clean(cup.get_text(" ", strip=True))
        if cup_text:
            out["cup_standings_text"] = cup_text
    return out
