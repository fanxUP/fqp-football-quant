"""从现有数据派生比赛上下文、出场分钟、伤停分类和来源记录。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any


def _minute(value: Any, default: int = 90) -> int:
    m = re.search(r"(\d+)", str(value or ""))
    if not m:
        return default
    return min(int(m.group(1)), 120)


def _kind(reason: str) -> str:
    text = str(reason or "")
    if "停赛" in text or "禁赛" in text:
        return "suspension"
    if "伤" in text or "损" in text or "病" in text or "痛" in text:
        return "injury"
    return "unknown"


def derive_injuries(conn) -> int:
    conn.execute("DELETE FROM match_injuries")
    rows = []
    for r in conn.execute(
        "SELECT match_id, payload FROM analysis_sections WHERE section='injuries'"
    ):
        try:
            items = json.loads(r["payload"] or "[]")
        except TypeError, ValueError:
            continue
        for i in items or []:
            rows.append(
                (
                    r["match_id"],
                    i.get("team_id"),
                    i.get("team_name"),
                    i.get("number"),
                    i.get("position"),
                    i.get("player_name"),
                    i.get("reason"),
                    _kind(i.get("reason")),
                )
            )
    conn.executemany(
        """INSERT OR REPLACE INTO match_injuries
           (match_id,team_id,team_name,number,position,player_name,reason,kind)
           VALUES (?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def derive_appearances(conn) -> int:
    conn.execute("DELETE FROM player_appearances")
    subs: dict[int, dict[str, list[int]]] = {}
    for r in conn.execute(
        "SELECT match_id, side, minute, player_name, assist_name FROM events "
        "WHERE event_type='换人'"
    ):
        minute = _minute(r["minute"], 90)
        entry = subs.setdefault(r["match_id"], {"in": {}, "out": {}})
        if r["player_name"]:
            entry["in"][str(r["player_name"]).strip()] = minute
        if r["assist_name"]:
            entry["out"][str(r["assist_name"]).strip()] = minute
    rows = []
    for r in conn.execute(
        """SELECT l.match_id, l.side, l.player_id, l.player_name, l.starter, l.position,
                  CASE WHEN l.side='home' THEN m.home_id ELSE m.away_id END team_id
           FROM lineups l JOIN matches m ON m.match_id=l.match_id"""
    ):
        if not r["player_id"]:
            continue
        name = str(r["player_name"] or "").strip()
        info = subs.get(r["match_id"], {"in": {}, "out": {}})
        if r["starter"]:
            minutes = info["out"].get(name, 90)
        else:
            on = info["in"].get(name)
            minutes = max(0, 90 - on) if on is not None else 0
        rows.append(
            (
                r["match_id"],
                r["team_id"],
                r["side"],
                r["player_id"],
                r["player_name"],
                r["starter"],
                minutes,
                r["position"],
            )
        )
    conn.executemany(
        """INSERT OR REPLACE INTO player_appearances
           (match_id,team_id,side,player_id,player_name,starter,minutes,position)
           VALUES (?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def _norm(text: str) -> str:
    return re.sub(r"[\s·.\-—_/]", "", str(text or "")).lower()


def derive_context(conn) -> int:
    home_venues: dict[int, str] = {}
    for r in conn.execute(
        """SELECT home_id, venue, COUNT(*) n FROM matches
           WHERE home_id IS NOT NULL AND venue IS NOT NULL AND venue<>''
           GROUP BY home_id, venue ORDER BY n DESC"""
    ):
        home_venues.setdefault(r[0], r[1])
    rows = []
    for r in conn.execute(
        """SELECT match_id, match_date, kickoff, home_id, away_id, venue
           FROM matches ORDER BY match_date, kickoff"""
    ):
        for side, team_id in (("home", r["home_id"]), ("away", r["away_id"])):
            if not team_id:
                continue
            prev = conn.execute(
                """SELECT match_date, home_id, away_id FROM matches
                   WHERE (home_id=? OR away_id=?) AND match_date < ?
                   ORDER BY match_date DESC LIMIT 1""",
                (team_id, team_id, r["match_date"]),
            ).fetchone()
            rest = None
            consecutive_away = 0
            if prev:
                try:
                    d1 = datetime.strptime(r["match_date"], "%Y-%m-%d")
                    d0 = datetime.strptime(prev["match_date"], "%Y-%m-%d")
                    rest = (d1 - d0).days
                except TypeError, ValueError:
                    pass
                if side == "away":
                    consecutive_away = 1
                    check = prev
                    for _ in range(5):
                        if check and check["away_id"] == team_id:
                            consecutive_away += 1
                            check = conn.execute(
                                """SELECT match_date, home_id, away_id FROM matches
                                   WHERE (home_id=? OR away_id=?) AND match_date < ?
                                   ORDER BY match_date DESC LIMIT 1""",
                                (team_id, team_id, check["match_date"]),
                            ).fetchone()
                        else:
                            break
            neutral = 0
            if side == "home" and r["venue"] and home_venues.get(team_id):
                neutral = int(
                    SequenceMatcher(None, _norm(r["venue"]), _norm(home_venues[team_id])).ratio()
                    < 0.6
                )
            rows.append((r["match_id"], team_id, side, rest, consecutive_away, neutral))
    conn.executemany(
        """INSERT OR REPLACE INTO match_context
           (match_id,team_id,side,rest_days,consecutive_away,is_neutral)
           VALUES (?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def derive_match_meta(conn) -> int:
    conn.execute(
        """UPDATE matches SET
             season=COALESCE(season,(SELECT season FROM league_results lr
                                      WHERE lr.match_id=matches.match_id LIMIT 1)),
             home_score_rt=CASE WHEN status_code IN (4,5) THEN home_score_rt ELSE home_score END,
             away_score_rt=CASE WHEN status_code IN (4,5) THEN away_score_rt ELSE away_score END,
             result_confirmed_at=COALESCE(result_confirmed_at,
               CASE WHEN status_text='完场' THEN updated_at END),
             first_fetched_at=COALESCE(first_fetched_at,updated_at),
             last_verified_at=COALESCE(last_verified_at,updated_at),
             revision=COALESCE(revision,1),
             source=COALESCE(source,'titan007')"""
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]


def derive_provenance(conn) -> int:
    conn.execute("DELETE FROM data_provenance")
    rows = []
    for r in conn.execute(
        "SELECT match_id, source, first_fetched_at, last_verified_at, revision FROM matches"
    ):
        rows.append(("match", r[0], r[1], None, r[2], r[3], r[4], None))
    for r in conn.execute("SELECT match_id, source, updated_at FROM odds"):
        rows.append(("odds", r[0], r[1], None, r[2], r[2], 1, None))
    for r in conn.execute("SELECT match_id, updated_at FROM analysis_sections"):
        rows.append(("analysis", r[0], "zq_analysis", None, r[1], r[1], 1, None))
    for r in conn.execute("SELECT lottery_match_id, updated_at FROM lottery_matches"):
        rows.append(("lottery_match", r[0], "sporttery", None, r[1], r[1], 1, None))
    conn.executemany(
        """INSERT OR REPLACE INTO data_provenance
           (entity_type,entity_id,source,published_at,first_fetched_at,
            last_verified_at,revision,missing_reason)
           VALUES (?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def derive_all(conn) -> dict[str, int]:
    return {
        "injuries": derive_injuries(conn),
        "appearances": derive_appearances(conn),
        "context": derive_context(conn),
        "cup_ties": derive_cup_ties(conn),
        "formats": derive_formats(conn),
        "matches": derive_match_meta(conn),
        "missing_fields": derive_missing_fields(conn),
        "provenance": derive_provenance(conn),
        "players": refresh_player_directory(conn),
        "counts": refresh_counts(conn),
    }


COUNT_TABLES = (
    "matches",
    "match_stats",
    "events",
    "lineups",
    "odds",
    "odds_history",
    "league_results",
    "league_standings",
    "scorers",
    "team_profiles",
    "team_squad",
    "player_stats",
    "jc_odds",
    "assets",
)


SQUAD_ID_OFFSET = 50_000_000


def _player_norm(name: Any) -> str:
    """队名以外，阵容里的球员名常带号码前缀（'13 犬饲智也'），归一化要去掉。"""
    text = re.sub(r"^\s*\d+\s*", "", str(name or ""))
    return re.sub(r"[\s·.\-—_/（）()]", "", text).lower()


def refresh_player_directory(conn) -> int:
    """把球员名单物化成单表：网页列表不必每次聚合 70 万行阵容。

    阵容表（tdl JS）和比赛阵容（live）用的是两套互不相干的球员ID，
    同一个号码会指向不同的人。所以目录以比赛阵容ID为准，阵容球员先按
    「球队+姓名」对齐到比赛ID；对不上的放进 SQUAD_ID_OFFSET 偏移区，
    免得页面把两个不同的人混成一条。
    """
    conn.execute("DELETE FROM player_directory")
    rows: dict[int, dict[str, Any]] = {}
    live_key: dict[tuple, int] = {}
    seen_match: dict[int, set] = {}
    for r in conn.execute(
        """SELECT l.player_id, l.player_name, l.birth, l.position, l.nationality,
                  CASE WHEN l.side='home' THEN m.home_id ELSE m.away_id END team_id,
                  m.match_id
           FROM lineups l JOIN matches m ON m.match_id=l.match_id
           WHERE l.player_id IS NOT NULL"""
    ):
        pid = int(r[0])
        entry = rows.get(pid)
        if entry is None:
            entry = rows[pid] = {
                "source": "lineup",
                "squad_id": None,
                "name": r[1],
                "team_id": r[5],
                "birth": None,
                "position": None,
                "nationality": None,
                "appearances": 0,
            }
        if r[6] is not None:
            seen_match.setdefault(pid, set()).add(r[6])
        entry["appearances"] = len(seen_match.get(pid, ()))
        for idx, key in ((2, "birth"), (3, "position"), (4, "nationality")):
            if not entry[key] and r[idx]:
                entry[key] = r[idx]
        if not entry["name"] and r[1]:
            entry["name"] = r[1]
        if r[5] is not None:
            entry["team_id"] = entry["team_id"] or r[5]
            live_key.setdefault((int(r[5]), _player_norm(r[1])), pid)
    for r in conn.execute(
        "SELECT team_id, player_id, name, birth, position, nationality FROM team_squad"
    ):
        team_id = int(r[0]) if r[0] is not None else None
        name, birth, position, nationality = r[2], r[3], r[4], r[5]
        pid = live_key.get((team_id, _player_norm(name)))
        if pid is not None:
            entry = rows[pid]
            if entry["squad_id"] is None:
                entry["squad_id"] = int(r[1])
            for key, value in (
                ("birth", birth),
                ("position", position),
                ("nationality", nationality),
            ):
                if not entry[key] and value:
                    entry[key] = value
            continue
        rows[SQUAD_ID_OFFSET + int(r[1])] = {
            "source": "squad",
            "squad_id": int(r[1]),
            "name": name,
            "team_id": team_id,
            "birth": birth,
            "position": position,
            "nationality": nationality,
            "appearances": 0,
        }
    now = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        """INSERT OR REPLACE INTO player_directory
           (player_id,source,squad_id,name,team_id,birth,position,nationality,
            appearances,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                pid,
                e["source"],
                e["squad_id"],
                e["name"],
                e["team_id"],
                e["birth"],
                e["position"],
                e["nationality"],
                e["appearances"],
                now,
            )
            for pid, e in rows.items()
        ],
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM player_directory").fetchone()[0]


def refresh_counts(conn) -> int:
    """缓存各表行数：大表 COUNT(*) 在低速存储上要扫描整表，首页不能现算。"""
    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for table in COUNT_TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        rows.append((table, n, now))
    conn.executemany(
        """INSERT OR REPLACE INTO data_counts (table_name,row_count,refreshed_at)
           VALUES (?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def derive_cup_ties(conn) -> int:
    rows = conn.execute(
        """SELECT lr.league_id, lr.season, lr.round, lr.home_id, lr.away_id,
                  lr.home_score, lr.away_score
           FROM league_results lr
           JOIN league_categories c ON c.league_id=lr.league_id
           WHERE (c.type IN ('cup','super_cup','tournament') OR COALESCE(c.tier,0)=0)
             AND lr.home_id IS NOT NULL AND lr.away_id IS NOT NULL"""
    ).fetchall()
    groups = {}
    for r in rows:
        key = (r[0], r[1], r[2], min(r[3], r[4]), max(r[3], r[4]))
        groups.setdefault(key, []).append(r)
    now = datetime.now().isoformat(timespec="seconds")
    out = []
    for (lid, season, rnd, a, b), legs in groups.items():
        if len(legs) < 2:
            continue
        sa = sb = 0
        complete = True
        for leg in legs:
            if leg[5] is None or leg[6] is None:
                complete = False
                break
            if leg[3] == a:
                sa += leg[5]
                sb += leg[6]
            else:
                sa += leg[6]
                sb += leg[5]
        if not complete:
            continue
        winner = a if sa > sb else b if sb > sa else None
        out.append((lid, season, rnd, a, b, len(legs), sa, sb, winner, now))
    conn.execute("DELETE FROM cup_ties")
    conn.executemany(
        """INSERT OR REPLACE INTO cup_ties
           (league_id,season,round,team_a,team_b,legs,score_a,score_b,winner_team_id,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        out,
    )
    conn.commit()
    return len(out)


def derive_formats(conn) -> int:
    import re as _re

    now = datetime.now().isoformat(timespec="seconds")
    cat = {
        r[0]: (r[1], r[2])
        for r in conn.execute("SELECT league_id, type, tier FROM league_categories")
    }
    rows = conn.execute("SELECT league_id, season, rules FROM league_info").fetchall()
    seen = set()
    out = []
    for lid, season, rules in rows:
        ctype, tier = cat.get(lid, (None, None))
        fmt = "cup" if ctype in ("cup", "super_cup", "tournament") else "league"
        text = rules or ""
        if "小组" in text and ("淘汰" in text or "淘汰赛" in text):
            fmt = "group_knockout"
        promo = _re.search(r"(?:升|晋级)[^。；]{0,10}?(\d+)\s*(?:名|队|支)", text)
        releg = _re.search(r"降[^。；]{0,10}?(\d+)\s*(?:名|队|支)", text)
        out.append(
            (
                lid,
                season,
                fmt,
                int(promo.group(1)) if promo else None,
                int(releg.group(1)) if releg else None,
                text or None,
                now,
            )
        )
        seen.add((lid, season))
    for lid, (ctype, _tier) in cat.items():
        if not any(k[0] == lid for k in seen):
            fmt = "cup" if ctype in ("cup", "super_cup", "tournament") else "league"
            season = (
                conn.execute(
                    "SELECT MAX(season) FROM league_standings WHERE league_id=?", (lid,)
                ).fetchone()[0]
                or "unknown"
            )
            out.append((lid, season, fmt, None, None, None, now))
    conn.execute("DELETE FROM competition_formats")
    conn.executemany(
        """INSERT OR REPLACE INTO competition_formats
           (league_id,season,format,promotion_slots,relegation_slots,notes,updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        out,
    )
    conn.commit()
    return len(out)


def derive_missing_fields(conn) -> int:
    conn.execute(
        "UPDATE matches SET timezone=COALESCE(timezone,'Asia/Shanghai'),"
        " source_record_id=COALESCE(source_record_id,CAST(match_id AS TEXT))"
    )
    conn.execute(
        "UPDATE team_squad SET roster_effective_at=COALESCE(roster_effective_at,"
        " (SELECT updated_at FROM team_profiles p WHERE p.team_id=team_squad.team_id))"
    )
    conn.execute(
        "UPDATE match_injuries SET missing_reason=COALESCE(missing_reason,"
        " '站方未提供伤病发生/预计复出时间')"
    )
    conn.execute("UPDATE predicted_lineups SET announced_at=COALESCE(announced_at,updated_at)")
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
