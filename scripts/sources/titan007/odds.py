"""Parsers for odds feeds and odds-change pages."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from . import jsfmt


def _f(v: Any) -> float | None:
    try:
        s = str(v).strip()
        if s == "" or s in ("-", "封"):
            return None
        return float(s)
    except TypeError, ValueError:
        return None


def _i(v: Any) -> int | None:
    try:
        return int(float(str(v).strip()))
    except TypeError, ValueError:
        return None


def parse_1x2d_time(value: str) -> str | None:
    """'2026,10-1,17,10,00,00' -> '2026-10-17 10:00:00'."""
    parts = (value or "").split(",")
    if len(parts) != 6:
        return None
    try:
        year = int(parts[0])
        month = int(parts[1].split("-")[0])
        day = int(parts[2])
        return f"{year:04d}-{month:02d}-{day:02d} {int(parts[3]):02d}:{int(parts[4]):02d}:{int(parts[5]):02d}"
    except ValueError, IndexError:
        return None


def parse_goal_feed(xml: str) -> list[dict[str, Any]]:
    """解析 ch_goalbf3.xml / goalBf3.xml（默认公司，通常是 Crow/皇冠）。"""
    out = []
    for raw in re.findall(r"<m>(.*?)</m>", xml, flags=re.S):
        f = raw.split(",")
        if len(f) < 13:
            continue
        match_id = _i(f[0])
        if not match_id:
            continue
        out.append(
            {
                "match_id": match_id,
                "source": "feed",
                "company_id": 3,
                "company_name": "Crow*",
                "asian_line": _f(f[2]),
                "asian_home": _f(f[3]),
                "asian_away": _f(f[4]),
                "euro_home": _f(f[6]),
                "euro_draw": _f(f[7]),
                "euro_away": _f(f[8]),
                "ou_line": _f(f[10]),
                "ou_over": _f(f[11]),
                "ou_under": _f(f[12]),
                "live_flag": _i(f[13]) if len(f) > 13 else None,
                "asian_open": _i(f[14]) if len(f) > 14 else None,
                "euro_open": _i(f[15]) if len(f) > 15 else None,
                "ou_open": _i(f[16]) if len(f) > 16 else None,
                "half_asian_line": _f(f[-2]) if len(f) >= 2 else None,
                "half_ou_line": _f(f[-1]) if len(f) >= 1 else None,
            }
        )
    return out


def parse_1x2d(text: str) -> dict[str, Any]:
    """解析 1x2d.titan007.com/{matchId}.js（百家欧赔 + 完整变化史）。"""
    game = jsfmt.extract_js_literal(text, "game") or []
    detail = jsfmt.extract_js_literal(text, "gameDetail") or []
    meta = {}
    for name in (
        "matchname",
        "matchname_cn",
        "MatchTime",
        "ScheduleID",
        "hometeam",
        "guestteam",
        "hometeam_cn",
        "guestteam_cn",
        "hometeamID",
        "guestteamID",
        "hOrder",
        "gOrder",
        "neutrality",
        "season",
        "sclassId",
        "sclassKind",
        "ifShow",
        "weatherIcon",
        "temperature",
        "venues_en",
    ):
        m = re.search(rf'var\s+{name}\s*=\s*"?([^";\n]*)"?;', text)
        if m:
            meta[name] = m.group(1).strip()

    companies: list[dict[str, Any]] = []
    id_to_company: dict[str, int] = {}
    for item in game:
        f = str(item).split("|")
        if len(f) < 22:
            continue
        cid = _i(f[0])
        if cid is None:
            continue
        id_to_company[str(f[1])] = cid
        companies.append(
            {
                "company_id": cid,
                "company_name": f[2],
                "company_name_cn": f[21],
                "odds_id": f[1],
                "initial_home": _f(f[3]),
                "initial_draw": _f(f[4]),
                "initial_away": _f(f[5]),
                "initial_return": _f(f[9]),
                "live_home": _f(f[10]),
                "live_draw": _f(f[11]),
                "live_away": _f(f[12]),
                "live_return": _f(f[16]),
                "initial_kelly_home": _f(f[24]) if len(f) > 24 else None,
                "initial_kelly_draw": _f(f[25]) if len(f) > 25 else None,
                "initial_kelly_away": _f(f[26]) if len(f) > 26 else None,
                "live_kelly_home": _f(f[17]),
                "live_kelly_draw": _f(f[18]),
                "live_kelly_away": _f(f[19]),
                "change_time": parse_1x2d_time(f[20]) or f[20],
            }
        )

    history: list[dict[str, Any]] = []
    for item in detail:
        s = str(item)
        odds_id, _, rest = s.partition("^")
        cid = id_to_company.get(odds_id)
        if cid is None:
            continue
        for seq, snap in enumerate(rest.split(";"), 1):
            f = snap.split("|")
            if len(f) < 4:
                continue
            history.append(
                {
                    "company_id": cid,
                    "seq": seq,
                    "home": _f(f[0]),
                    "line": _f(f[1]),
                    "away": _f(f[2]),
                    "change_time": f[3],
                    "live_kelly_home": _f(f[4]) if len(f) > 4 else None,
                    "live_kelly_draw": _f(f[5]) if len(f) > 5 else None,
                    "live_kelly_away": _f(f[6]) if len(f) > 6 else None,
                }
            )
    return {"meta": meta, "companies": companies, "history": history}


def parse_vip_change(html: str) -> list[dict[str, Any]]:
    """解析 vip/changeDetail/*.aspx 的赔率变化表。

    返回行字段：minute, score, home, line, away, change_time, status。
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        texts = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in tds]
        if not re.fullmatch(r"\d+(?:\+\d+)?", texts[0]):
            continue
        if len(texts) >= 7:
            home, line, away = texts[2], texts[3], texts[4]
            change_time, status = texts[5], texts[6]
        else:
            home = line = away = None
            change_time, status = texts[-2], texts[-1]
        rows.append(
            {
                "seq": len(rows) + 1,
                "minute": texts[0],
                "score": texts[1],
                "home": _f(home),
                "line": line,
                "away": _f(away),
                "change_time": change_time,
                "status": status,
            }
        )
    return rows


def parse_league_odds_ajax(text: str) -> dict[str, Any]:
    """解析 LeagueOddsAjax 返回的 oddsData。"""
    out: dict[str, Any] = {}
    for kind, match_id, raw in re.findall(
        r'oddsData\["([OLT])_(\d+)"\]\s*=\s*(\[.*?\]);', text, flags=re.S
    ):
        parsed = jsfmt.js_literal(raw)
        if parsed is not None:
            out.setdefault(match_id, {})[{"O": "europe", "L": "asian", "T": "overunder"}[kind]] = (
                parsed
            )
    return out
