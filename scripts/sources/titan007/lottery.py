"""中国体彩竞彩数据抓取与球队映射。"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlencode

LOTTERY_API = "https://webapi.sporttery.cn/gateway/uniform/football/getUniformMatchResultV1.qry"
REFERER = "https://www.lottery.gov.cn/jc/zqsgkj/"


def _float(value) -> float | None:
    try:
        return float(str(value).strip())
    except TypeError, ValueError:
        return None


def _int(value) -> int | None:
    try:
        return int(str(value).strip())
    except TypeError, ValueError:
        return None


def _score(value) -> tuple[int | None, int | None]:
    m = re.fullmatch(r"(\d+)\s*:\s*(\d+)", str(value or "").strip())
    return (_int(m.group(1)), _int(m.group(2))) if m else (None, None)


def normalize_name(name: Any) -> str:
    s = str(name or "").strip()
    s = s.replace("（", "(").replace("）", ")")
    for suffix in ("足球俱乐部", "俱乐部", "足球会", "足球队"):
        s = s.replace(suffix, "")
    for suffix in ("亚运男足", "亚运会男足", "亚足", "亚运", "国奥", "男足"):
        s = s.replace(suffix, "")
    s = re.sub(r"[\s·.\-—_/]", "", s)
    return s.lower()


def sync_lottery(conn, client, start: str, end: str) -> dict[str, int]:
    page_no, matches, teams, pages = 1, 0, 0, 1
    while page_no <= pages:
        params = {
            "matchBeginDate": start,
            "matchEndDate": end,
            "leagueId": "",
            "pageSize": 100,
            "pageNo": page_no,
            "isFix": 0,
            "matchPage": 1,
            "pcOrWap": 1,
        }
        raw = client.get(LOTTERY_API + "?" + urlencode(params), referer=REFERER)
        value = (json.loads(raw) or {}).get("value") or {}
        pages = int(value.get("pages") or 0)
        rows = value.get("matchResult") or []
        now = datetime.now().isoformat(timespec="seconds")
        for r in rows:
            hs, aws = _score(r.get("sectionsNo999"))
            conn.execute(
                """INSERT INTO lottery_matches
                   (lottery_match_id,match_date,match_num,league_id,league_name,
                    home_team_id,home_team,home_full_name,away_team_id,away_team,
                    away_full_name,home_score,away_score,half_score,odds_h,odds_d,odds_a,
                    goal_line,win_flag,status,pool_status,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(lottery_match_id) DO UPDATE SET
                     match_date=excluded.match_date, match_num=excluded.match_num,
                     league_id=excluded.league_id, league_name=excluded.league_name,
                     home_team_id=excluded.home_team_id, home_team=excluded.home_team,
                     home_full_name=excluded.home_full_name, away_team_id=excluded.away_team_id,
                     away_team=excluded.away_team, away_full_name=excluded.away_full_name,
                     home_score=excluded.home_score, away_score=excluded.away_score,
                     half_score=excluded.half_score, odds_h=excluded.odds_h,
                     odds_d=excluded.odds_d, odds_a=excluded.odds_a,
                     goal_line=excluded.goal_line, win_flag=excluded.win_flag,
                     status=excluded.status, pool_status=excluded.pool_status,
                     updated_at=excluded.updated_at""",
                (
                    _int(r.get("matchId")),
                    r.get("matchDate"),
                    r.get("matchNumStr"),
                    _int(r.get("leagueId")),
                    r.get("leagueName"),
                    _int(r.get("homeTeamId")),
                    r.get("homeTeam"),
                    r.get("allHomeTeam"),
                    _int(r.get("awayTeamId")),
                    r.get("awayTeam"),
                    r.get("allAwayTeam"),
                    hs,
                    aws,
                    r.get("sectionsNo1"),
                    _float(r.get("h")),
                    _float(r.get("d")),
                    _float(r.get("a")),
                    _float(r.get("goalLine")),
                    r.get("winFlag"),
                    r.get("matchResultStatus"),
                    r.get("poolStatus"),
                    now,
                ),
            )
            matches += 1
            for tid, name, full in (
                (_int(r.get("homeTeamId")), r.get("homeTeam"), r.get("allHomeTeam")),
                (_int(r.get("awayTeamId")), r.get("awayTeam"), r.get("allAwayTeam")),
            ):
                if tid and name:
                    conn.execute(
                        """INSERT INTO lottery_teams
                           (lottery_team_id,name,full_name,league_name,updated_at)
                           VALUES (?,?,?,?,?)
                           ON CONFLICT(lottery_team_id) DO UPDATE SET
                             name=excluded.name, full_name=excluded.full_name,
                             league_name=COALESCE(excluded.league_name,lottery_teams.league_name),
                             updated_at=excluded.updated_at""",
                        (tid, name, full, r.get("leagueName"), now),
                    )
                    teams += 1
        conn.commit()
        page_no += 1
    return {"matches": matches, "team_rows": teams, "pages": pages}


def _team_index(conn) -> dict[str, dict[int, str]]:
    index: dict[str, dict[int, str]] = {}
    for sql in (
        "SELECT home_id, home_name FROM matches WHERE home_id IS NOT NULL",
        "SELECT away_id, away_name FROM matches WHERE away_id IS NOT NULL",
        "SELECT team_id, name FROM league_teams WHERE name IS NOT NULL",
        "SELECT team_id, name_traditional FROM league_teams WHERE name_traditional IS NOT NULL",
        "SELECT team_id, name FROM team_profiles WHERE name IS NOT NULL",
        "SELECT team_id, name_traditional FROM team_profiles WHERE name_traditional IS NOT NULL",
        "SELECT team_id, name_en FROM team_profiles WHERE name_en IS NOT NULL",
    ):
        for tid, name in conn.execute(sql):
            key = normalize_name(name)
            if tid and key:
                index.setdefault(key, {}).setdefault(tid, name)
    return index


def _team_leagues(conn) -> dict[int, set]:
    out: dict[int, set] = {}
    for tid, league in conn.execute(
        """SELECT lt.team_id, l.name_simplified FROM league_teams lt
           JOIN leagues l ON l.league_id=lt.league_id WHERE l.name_simplified IS NOT NULL"""
    ):
        out.setdefault(tid, set()).add(normalize_name(league))
    for tid, league in conn.execute(
        """SELECT home_id, league_name FROM matches WHERE home_id IS NOT NULL AND league_name IS NOT NULL
           UNION ALL SELECT away_id, league_name FROM matches WHERE away_id IS NOT NULL AND league_name IS NOT NULL"""
    ):
        out.setdefault(tid, set()).add(normalize_name(league))
    return out


def _league_score(tid, league_norm, team_leagues) -> float:
    if not league_norm:
        return 0.0
    best = 0.0
    for name in team_leagues.get(tid, ()):
        best = max(best, SequenceMatcher(None, league_norm, name).ratio())
    return best


def _audience_penalty(lottery_name: str, titan_name: str) -> float:
    penalty = 0.0
    if "女" not in lottery_name and "女" in titan_name:
        penalty += 0.3
    if not re.search(r"U\d{2}", lottery_name, re.I) and re.search(r"U\d{2}", titan_name, re.I):
        penalty += 0.3
    if "后备" not in lottery_name and "后备" in titan_name:
        penalty += 0.3
    return penalty


def map_teams(conn) -> dict[str, int]:
    index = _team_index(conn)
    aliases = {
        normalize_name(r["lottery_name"]): r["titan_team_id"]
        for r in conn.execute("SELECT lottery_name, titan_team_id FROM team_aliases")
        if r["lottery_name"] and r["titan_team_id"]
    }
    now = datetime.now().isoformat(timespec="seconds")
    id_to_name = {}
    for teams in index.values():
        for tid, nm in teams.items():
            id_to_name.setdefault(tid, nm)
    team_leagues = _team_leagues(conn)
    stats = {"exact": 0, "alias": 0, "manual": 0, "fuzzy": 0, "ambiguous": 0, "unmatched": 0}
    for team in conn.execute("SELECT * FROM lottery_teams ORDER BY lottery_team_id"):
        norm = normalize_name(team["full_name"] or team["name"])
        name_norm = normalize_name(team["name"])
        league_norm = normalize_name(team["league_name"])
        titan_id = aliases.get(norm) or aliases.get(name_norm)
        method, confidence, status = None, None, None
        titan_name = None
        if titan_id:
            titan_name = id_to_name.get(titan_id)
            method, confidence, status = "manual", 1.0, "mapped"
        else:
            candidates: dict[int, str] = {}
            for key in (norm, name_norm):
                for tid, nm in index.get(key, {}).items():
                    candidates.setdefault(tid, nm)
            if len(candidates) == 1:
                titan_id, titan_name = next(iter(candidates.items()))
                method, confidence, status = "exact", 0.99, "mapped"
            elif len(candidates) > 1:
                ranked = sorted(
                    candidates.items(),
                    key=lambda kv: (
                        _audience_penalty(norm, kv[1]),
                        -_league_score(kv[0], league_norm, team_leagues),
                        kv[0],
                    ),
                )
                best_tid, best_name = ranked[0]
                best_pen = _audience_penalty(norm, best_name)
                best_league = _league_score(best_tid, league_norm, team_leagues)
                if len(ranked) == 1:
                    clear = True
                else:
                    sec_name = ranked[1][1]
                    sec_pen = _audience_penalty(norm, sec_name)
                    sec_league = _league_score(ranked[1][0], league_norm, team_leagues)
                    clear = (best_pen + 0.25 <= sec_pen) or (best_league >= sec_league + 0.12)
                titan_id, titan_name = best_tid, best_name
                method = "exact"
                confidence = 0.95 if clear else 0.9
                status = "mapped" if clear else "ambiguous"
            else:
                best: dict[int, tuple[float, str]] = {}
                for key, teams in index.items():
                    score = SequenceMatcher(None, norm or name_norm, key).ratio()
                    for tid, nm in teams.items():
                        if score > best.get(tid, (0.0, ""))[0]:
                            best[tid] = (score, nm)
                ranked = []
                for tid, (score, nm) in best.items():
                    composite = (
                        score
                        + 0.15 * _league_score(tid, league_norm, team_leagues)
                        - _audience_penalty(norm, nm)
                    )
                    ranked.append((composite, tid, nm))
                ranked.sort(reverse=True)
                if ranked:
                    score, tid, nm = ranked[0]
                    second = ranked[1][0] if len(ranked) > 1 else 0.0
                    titan_id, titan_name = tid, nm
                    if score >= 0.8 and score - second >= 0.03:
                        method, confidence, status = "fuzzy", min(score, 1.0), "mapped"
                    elif score >= 0.62:
                        method, confidence, status = "fuzzy", score, "ambiguous"
                    else:
                        method, confidence, status = "fuzzy", score, "unmatched"
                else:
                    method, confidence, status = "fuzzy", 0.0, "unmatched"
        if status == "mapped":
            stats[method] += 1
        else:
            stats[status] += 1
        conn.execute(
            """INSERT INTO team_mapping
               (lottery_team_id,titan_team_id,lottery_name,titan_name,
                confidence,method,status,updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(lottery_team_id) DO UPDATE SET
                 titan_team_id=excluded.titan_team_id, lottery_name=excluded.lottery_name,
                 titan_name=excluded.titan_name, confidence=excluded.confidence,
                 method=excluded.method, status=excluded.status,
                 updated_at=excluded.updated_at""",
            (
                team["lottery_team_id"],
                titan_id,
                team["full_name"] or team["name"],
                titan_name,
                confidence,
                method,
                status,
                now,
            ),
        )
    conn.commit()
    return stats


def link_matches(conn, start: str, end: str) -> dict[str, int]:
    """把竞彩场次关联到 titan007 比赛。"""
    mapping, mapping_names = {}, {}
    for r in conn.execute(
        "SELECT lottery_team_id, titan_team_id, titan_name FROM team_mapping "
        "WHERE titan_team_id IS NOT NULL AND status='mapped'"
    ):
        mapping[r["lottery_team_id"]] = r["titan_team_id"]
        mapping_names[r["lottery_team_id"]] = r["titan_name"]
    stats = {"jc": 0, "ids": 0, "pair": 0, "name": 0, "unlinked": 0}
    rows = conn.execute(
        """SELECT * FROM lottery_matches
           WHERE match_date BETWEEN ? AND ? ORDER BY match_date""",
        (start, end),
    ).fetchall()
    for row in rows:
        titan_id, link_type = None, None
        found = conn.execute(
            """SELECT match_id FROM matches WHERE lottery_jc=?
               AND match_date BETWEEN date(?, '-1 day') AND date(?, '+1 day')
               LIMIT 1""",
            (row["match_num"], row["match_date"], row["match_date"]),
        ).fetchone()
        if found:
            titan_id, link_type = found["match_id"], "jc"
        home_id = mapping.get(row["home_team_id"])
        away_id = mapping.get(row["away_team_id"])
        if not titan_id and home_id and away_id:
            found = conn.execute(
                """SELECT match_id FROM matches
                   WHERE home_id=? AND away_id=?
                     AND match_date BETWEEN date(?, '-1 day') AND date(?, '+1 day')
                   LIMIT 1""",
                (home_id, away_id, row["match_date"], row["match_date"]),
            ).fetchone()
            if found:
                titan_id, link_type = found["match_id"], "ids"
        if not titan_id and (home_id or away_id):
            base_id = home_id or away_id
            column = "home_id" if home_id else "away_id"
            other = row["away_full_name"] if home_id else row["home_full_name"]
            other_norm = normalize_name(other)
            for cand in conn.execute(
                f"""SELECT match_id, home_name, away_name, home_id, away_id FROM matches
                    WHERE {column}=? AND match_date BETWEEN date(?, '-1 day') AND date(?, '+1 day')""",
                (base_id, row["match_date"], row["match_date"]),
            ):
                cand_name = cand["away_name"] if home_id else cand["home_name"]
                if SequenceMatcher(None, other_norm, normalize_name(cand_name)).ratio() >= 0.8:
                    titan_id, link_type = cand["match_id"], "pair"
                    break
        if not titan_id:
            home_norm = normalize_name(
                mapping_names.get(row["home_team_id"]) or row["home_full_name"]
            )
            away_norm = normalize_name(
                mapping_names.get(row["away_team_id"]) or row["away_full_name"]
            )
            for cand in conn.execute(
                """SELECT match_id, home_name, away_name FROM matches
                   WHERE match_date BETWEEN date(?, '-1 day') AND date(?, '+1 day')""",
                (row["match_date"], row["match_date"]),
            ):
                if (
                    SequenceMatcher(None, home_norm, normalize_name(cand["home_name"])).ratio()
                    >= 0.9
                    and SequenceMatcher(None, away_norm, normalize_name(cand["away_name"])).ratio()
                    >= 0.9
                ):
                    titan_id, link_type = cand["match_id"], "name"
                    break
        if titan_id:
            if home_id or away_id:
                conn.execute(
                    """UPDATE matches SET
                         home_id=COALESCE(home_id, ?), away_id=COALESCE(away_id, ?)
                       WHERE match_id=?""",
                    (home_id, away_id, titan_id),
                )
        if titan_id:
            conn.execute(
                "UPDATE lottery_matches SET titan_match_id=?, link_type=? WHERE lottery_match_id=?",
                (titan_id, link_type, row["lottery_match_id"]),
            )
            stats[link_type] += 1
        else:
            conn.execute(
                "UPDATE lottery_matches SET titan_match_id=NULL, link_type=NULL "
                "WHERE lottery_match_id=?",
                (row["lottery_match_id"],),
            )
            stats["unlinked"] += 1
    conn.commit()
    return stats


def write_review(conn, path: str, limit: int | None = None) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    rows = conn.execute(
        """SELECT m.*, t.name lottery_short, t.full_name, t.league_name
           FROM team_mapping m JOIN lottery_teams t ON t.lottery_team_id=m.lottery_team_id
           WHERE m.status IN ('ambiguous','unmatched')
           ORDER BY m.status, m.confidence DESC"""
    ).fetchall()
    if limit:
        rows = rows[:limit]
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "lottery_team_id",
                "lottery_name",
                "full_name",
                "league",
                "status",
                "confidence",
                "candidate_titan_id",
                "candidate_titan_name",
                "method",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r["lottery_team_id"],
                    r["lottery_name"],
                    r["full_name"],
                    r["league_name"],
                    r["status"],
                    r["confidence"],
                    r["titan_team_id"],
                    r["titan_name"],
                    r["method"],
                ]
            )
    return len(rows)


def import_aliases(conn, path: str) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    with open(path, encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("lottery_name") or "").strip()
            tid = _int(row.get("titan_team_id"))
            if not name or not tid:
                continue
            conn.execute(
                """INSERT INTO team_aliases (lottery_name,titan_team_id,note,updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(lottery_name) DO UPDATE SET
                     titan_team_id=excluded.titan_team_id, note=excluded.note,
                     updated_at=excluded.updated_at""",
                (name, tid, row.get("note"), now),
            )
            n += 1
    conn.commit()
    return n


def sync_lottery_odds(conn) -> int:
    """把竞彩胜平负赔率写入 odds 表，company_id=0（中国体彩）。"""
    rows = conn.execute(
        """SELECT titan_match_id, odds_h, odds_d, odds_a, updated_at
           FROM lottery_matches
           WHERE titan_match_id IS NOT NULL
             AND odds_h IS NOT NULL AND odds_d IS NOT NULL AND odds_a IS NOT NULL"""
    ).fetchall()
    payload = []
    now = datetime.now().isoformat(timespec="seconds")
    for r in rows:
        payload.append(
            (
                r["titan_match_id"],
                0,
                "中国体育彩票竞彩",
                "europe",
                "lottery",
                r["odds_h"],
                r["odds_d"],
                r["odds_a"],
                r["odds_h"],
                r["odds_d"],
                r["odds_a"],
                r["updated_at"] or now,
            )
        )
    conn.executemany(
        """INSERT INTO odds (match_id,company_id,company_name,odds_type,source,
             initial_home,initial_line,initial_away,live_home,live_line,live_away,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(match_id,company_id,odds_type,source) DO UPDATE SET
             company_name=excluded.company_name, initial_home=excluded.initial_home,
             initial_line=excluded.initial_line, initial_away=excluded.initial_away,
             live_home=excluded.live_home, live_line=excluded.live_line,
             live_away=excluded.live_away, updated_at=excluded.updated_at""",
        payload,
    )
    conn.commit()
    return len(payload)
