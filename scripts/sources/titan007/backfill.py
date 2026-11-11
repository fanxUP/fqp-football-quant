"""离线回填：用已知的队名→ID 词典补全 matches 里缺失的 home_id/away_id。

历史赛果页只给中文队名，早期入库时没有带队伍ID。同一个联赛里队名很稳定，
所以拿「已有ID的比赛 + 联赛队伍表 + 球队资料」里出现过的队名反查即可，
不需要再请求站点。名字对应到多个ID的一律放弃，交给人工别名。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime


def _add_from_analysis(conn, add) -> None:
    """赛前分析里的往绩/近期战绩数组自带 home_id/away_id，是队名的另一个来源。"""
    for row in conn.execute(
        """SELECT payload FROM analysis_sections
           WHERE section IN ('form_home','form_away','h2h','next_matches')"""
    ):
        try:
            items = json.loads(row[0] or "[]")
        except TypeError, ValueError:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            add(item.get("home_name"), item.get("home_id"))
            add(item.get("away_name"), item.get("away_id"))


def build_name_index(conn) -> tuple[dict[str, int], list[str]]:
    """返回 (唯一队名→ID, 冲突队名列表)。权重只用于同分排序，不参与决策。"""
    votes: dict[str, dict[int, int]] = {}

    def add(name, team_id, weight: int = 1) -> None:
        key = str(name or "").strip()
        if not key or not team_id:
            return
        bucket = votes.setdefault(key, {})
        bucket[int(team_id)] = bucket.get(int(team_id), 0) + weight

    for r in conn.execute("SELECT home_id, home_name FROM matches WHERE home_id IS NOT NULL"):
        add(r[1], r[0])
    for r in conn.execute("SELECT away_id, away_name FROM matches WHERE away_id IS NOT NULL"):
        add(r[1], r[0])
    for r in conn.execute("SELECT team_id, name, name_traditional FROM league_teams"):
        add(r[1], r[0], 2)
        add(r[2], r[0], 2)
    for r in conn.execute("SELECT team_id, name, name_traditional FROM team_profiles"):
        add(r[1], r[0], 2)
        add(r[2], r[0], 2)
    for r in conn.execute("SELECT titan_team_id, titan_name, display_name FROM team_catalog"):
        add(r[1], r[0], 2)
        add(r[2], r[0], 2)
    _add_from_analysis(conn, add)

    resolved: dict[str, int] = {}
    ambiguous: list[str] = []
    for name, bucket in votes.items():
        if len(bucket) == 1:
            resolved[name] = next(iter(bucket))
        else:
            ambiguous.append(name)
    return resolved, sorted(ambiguous)


def _norm_name(name: str) -> str:
    text = re.sub(r"[（(][^)）]*[)）]", "", str(name or ""))
    return re.sub(r"[\s·.\-—_/]", "", text).lower()


def _lookup(index: dict[str, int], name) -> int | None:
    text = str(name or "").strip()
    if not text:
        return None
    return index.get(text) or index.get(_norm_name(text))


def _char_ratio(a: str, b: str) -> float:
    """按字符重算相似度：国际迈阿密 / 迈阿密国际 这种颠倒顺序也能认出来。"""
    if not a or not b:
        return 0.0
    common = sum((Counter(a) & Counter(b)).values())
    return 2 * common / (len(a) + len(b))


def _league_teams(conn) -> dict[int, set]:
    out: dict[int, set] = {}
    for lid, tid, name in conn.execute("SELECT league_id, team_id, name FROM league_teams"):
        key = _norm_name(name)
        if lid is None or not key:
            continue
        out.setdefault(int(lid), set()).add((int(tid), key))
    return out


def fuzzy_pick(name: str, candidates: set) -> int | None:
    """在同一联赛的队伍里找唯一候选。

    先看包含关系（纳什威尔/纳什威尔SC），再看字符重合度（国际迈阿密/迈阿密国际）。
    字符分数要求"最高分 ≥0.6 且领先第二名 0.25"，避免把两支不同的队认成一支。
    """
    key = _norm_name(name)
    if len(key) < 2:
        return None
    hits = {tid for tid, cname in candidates if key in cname or cname in key}
    if len(hits) == 1:
        only = next(iter(hits))
        rivals = [_char_ratio(key, cname) for tid, cname in candidates if tid != only]
        return only if all(r < 0.8 for r in rivals) else None
    if hits:
        return None
    scored = sorted(((_char_ratio(key, cname), tid) for tid, cname in candidates), reverse=True)
    if not scored:
        return None
    best, team_id = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best >= 0.6 and best - second >= 0.25:
        return team_id
    return None


def _apply_fuzzy(conn, rows, updates) -> int:
    """对仍然缺 ID 的比赛做同联赛模糊匹配，就地补进 updates，返回新增的两侧齐全场次。"""
    league_teams = _league_teams(conn)
    slot = {u[2]: i for i, u in enumerate(updates)}
    extra = 0
    for r in rows:
        match_id, league_id = r[0], r[1]
        idx = slot.get(match_id)
        home, away = (updates[idx][0], updates[idx][1]) if idx is not None else (r[2], r[3])
        if home and away:
            continue
        candidates = league_teams.get(int(league_id or 0), set())
        if not candidates:
            continue
        old = (home, away)
        home = home or fuzzy_pick(r[4], candidates)
        away = away or fuzzy_pick(r[5], candidates)
        if (home, away) == old:
            continue
        if idx is not None:
            updates[idx] = (home, away, match_id)
        else:
            slot[match_id] = len(updates)
            updates.append((home, away, match_id))
        if home and away:
            extra += 1
    return extra


def _with_normalized(resolved: dict[str, int]) -> dict[str, int]:
    """给词典加上去掉括号注释/空格后的键，用来匹配“利物浦(中)”这类写法。

    归一化后撞名的（不同ID）直接丢掉，只保留原来能唯一对应的键。
    """
    norm: dict[str, int] = {}
    clash = set()
    for name, team_id in resolved.items():
        key = _norm_name(name)
        if not key:
            continue
        if key in norm and norm[key] != team_id:
            clash.add(key)
        norm[key] = team_id
    out = dict(resolved)
    for key, team_id in norm.items():
        if key not in clash:
            out.setdefault(key, team_id)
    return out


def backfill_team_ids(conn, dry_run: bool = False, fuzzy: bool = False) -> dict[str, int]:
    """把能唯一定位的队名写回 matches。返回统计，dry_run 时只统计不落库。

    fuzzy=True 时，对仍然缺 ID 的比赛在同一联赛的队伍里再找一次
    （蒙特利尔冲击 vs CF蒙特利尔、纽约城(中) vs 纽约城 这类译名差异）。
    """
    resolved, ambiguous = build_name_index(conn)
    lookup = _with_normalized(resolved)
    rows = conn.execute(
        """SELECT match_id, league_id, home_id, away_id, home_name, away_name FROM matches
           WHERE home_id IS NULL OR away_id IS NULL"""
    ).fetchall()
    updates = []
    for r in rows:
        home = r[2] or _lookup(lookup, r[4])
        away = r[3] or _lookup(lookup, r[5])
        if home != r[2] or away != r[3]:
            updates.append((home, away, r[0]))
    filled = sum(1 for u in updates if u[0] and u[1])
    if fuzzy:
        filled += _apply_fuzzy(conn, rows, updates)
    if not dry_run and updates:
        conn.executemany("UPDATE matches SET home_id=?, away_id=? WHERE match_id=?", updates)
        conn.commit()
    return {
        "names": len(resolved),
        "ambiguous_names": len(ambiguous),
        "scanned": len(rows),
        "updated": len(updates),
        "fully_linked": filled,
        "still_open": len(rows) - filled,
    }


def season_years(season: str) -> set:
    """'2025-2026' → {2025, 2026}；'2026' → {2026}。"""
    years = [int(y) for y in re.findall(r"\d{4}", str(season or ""))]
    if len(years) >= 2:
        return set(range(years[0], years[1] + 1))
    return set(years)


def _season_span(season: str) -> tuple[date, date] | None:
    """赛季覆盖的日期区间：跨年赛季按 7 月切分，单年赛季按自然年。"""
    years = sorted(int(y) for y in re.findall(r"\d{4}", str(season or "")))
    if len(years) >= 2:
        return date(years[0], 7, 1), date(years[1], 7, 1)
    if years:
        return date(years[0], 1, 1), date(years[0] + 1, 1, 1)
    return None


def seasons_for_dates(seasons: list[str], dates: list[str]) -> list[str]:
    """挑出能覆盖这些比赛日期的赛季，避免把整年两个赛季都抓一遍。"""
    spans = [(s, _season_span(s)) for s in seasons]
    wanted = []
    for text in dates:
        try:
            day = datetime.strptime(str(text)[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        for season, span in spans:
            if span and span[0] <= day < span[1] and season not in wanted:
                wanted.append(season)
    return wanted


def missing_league_seasons(conn) -> list[tuple[int, int, int]]:
    """比赛里有、但联赛赛果表还没抓过的 (league_id, 年份, 比赛数)。

    没 ID 的比赛多半来自没抓过的老赛季：抓一次该赛季的联赛 JS，
    arrTeam 会带回那一年的队伍名和ID，队名词典才补得上。
    """
    covered: dict[int, set] = {}
    for lid, season in conn.execute("SELECT DISTINCT league_id, season FROM league_results"):
        if lid is not None:
            covered.setdefault(int(lid), set()).update(season_years(season))
    out = []
    for lid, year, n in conn.execute(
        """SELECT league_id, CAST(substr(match_date,1,4) AS INTEGER), COUNT(*)
           FROM matches WHERE home_id IS NULL OR away_id IS NULL
           GROUP BY league_id, 2 ORDER BY 3 DESC"""
    ):
        if lid is None or year is None:
            continue
        if int(year) not in covered.get(int(lid), set()):
            out.append((int(lid), int(year), int(n)))
    return out
