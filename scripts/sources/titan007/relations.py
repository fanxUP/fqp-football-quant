"""联赛积分榜完整性与升降级关系推断。"""

from __future__ import annotations

import json

from . import leagues as leagues_parser
from . import store
from .client import AcquisitionStopped, record_operation_failure

SUBLEAGUE_URL = "https://zq.titan007.com/cn/subleague.aspx?sclassid={league_id}"
SEA_URL = "https://zq.titan007.com/jsData/LeagueSeason/sea{league_id}.js"
LEAGUE_JS_URL = "https://zq.titan007.com/jsData/matchResult/{season}/s{league_id}_{sub_id}.js"
LEAGUE_JS_PLAIN = "https://zq.titan007.com/jsData/matchResult/{season}/s{league_id}.js"
CUP_JS_URL = "https://zq.titan007.com/jsData/matchResult/{season}/c{league_id}.js"


def previous_season(season: str) -> str | None:
    s = str(season or "").strip()
    if not s:
        return None
    if "-" in s:
        start = s.split("-")[0]
        try:
            y = int(start)
        except ValueError:
            return None
        return f"{y - 1}-{y}"
    try:
        return str(int(s) - 1)
    except ValueError:
        return None


def _season_start(season: str) -> int:
    try:
        return int(str(season).split("-")[0])
    except TypeError, ValueError:
        return 0


def fetch_previous_standings(conn, client, limit: int | None = None) -> dict[str, int]:
    rows = conn.execute(
        "SELECT league_id, MAX(season) season FROM league_standings GROUP BY league_id"
    ).fetchall()
    targets = []
    for r in rows:
        prev = previous_season(r["season"])
        if not prev:
            continue
        exists = conn.execute(
            "SELECT 1 FROM league_standings WHERE league_id=? AND season=? LIMIT 1",
            (r["league_id"], prev),
        ).fetchone()
        if not exists:
            targets.append((r["league_id"], prev))
    if limit:
        targets = targets[:limit]
    ok = skip = 0
    for i, (league_id, season) in enumerate(targets, 1):
        try:
            sub_html = client.get(
                SUBLEAGUE_URL.format(league_id=league_id),
                referer="https://zq.titan007.com/",
            )
            sub_id = leagues_parser.parse_sub_league_id(sub_html)
            is_cup = not sub_id and f"/c{league_id}.js" in sub_html
            if is_cup:
                data = leagues_parser.parse_cup_js(
                    client.get(
                        CUP_JS_URL.format(season=season, league_id=league_id),
                        referer="https://zq.titan007.com/",
                    )
                )
                data["league"] = leagues_parser.cup_league_info(data)
                standings = leagues_parser.normalize_cup_standings(data)
            else:
                url = (
                    LEAGUE_JS_URL.format(season=season, league_id=league_id, sub_id=sub_id)
                    if sub_id
                    else LEAGUE_JS_PLAIN.format(season=season, league_id=league_id)
                )
                data = leagues_parser.parse_league_js(
                    client.get(url, referer="https://zq.titan007.com/")
                )
                standings = leagues_parser.normalize_standings(data)
            if standings:
                store.save_league(conn, league_id, season, data, [], standings, {})
                ok += 1
            else:
                skip += 1
            if i % 20 == 0:
                print(f"[{i}/{len(targets)}] ok={ok} skip={skip}", flush=True)
        except AcquisitionStopped:
            raise
        except Exception as exc:
            record_operation_failure()
            skip += 1
            print(f"[{i}/{len(targets)}] {league_id} {season}: skip {exc}", flush=True)
    return {"ok": ok, "skip": skip, "targets": len(targets)}


def _team_names(conn) -> dict[int, str]:
    names: dict[int, str] = {}
    for tid, name in conn.execute("SELECT team_id, name FROM team_profiles WHERE name IS NOT NULL"):
        names[tid] = name
    for tid, name in conn.execute("SELECT team_id, name FROM league_teams WHERE name IS NOT NULL"):
        names.setdefault(tid, name)
    for tid, name in conn.execute(
        "SELECT home_id, home_name FROM matches WHERE home_id IS NOT NULL "
        "UNION ALL SELECT away_id, away_name FROM matches WHERE away_id IS NOT NULL"
    ):
        names.setdefault(tid, name)
    return names


def build_seasons(conn) -> int:
    names = _team_names(conn)
    conn.execute("DELETE FROM team_league_seasons")
    rows = []
    for r in conn.execute("SELECT team_id, league_id, season, rank, points FROM league_standings"):
        rows.append((r[0], r[1], r[2], names.get(r[0]), r[3], r[4]))
    conn.executemany(
        """INSERT OR REPLACE INTO team_league_seasons
           (team_id,league_id,season,team_name,rank,points) VALUES (?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def _league_tiers(conn) -> dict[int, int]:
    return {r[0]: r[1] or 0 for r in conn.execute("SELECT league_id, tier FROM league_categories")}


def _league_names(conn) -> dict[int, str]:
    return {r[0]: r[1] for r in conn.execute("SELECT league_id, name_simplified FROM leagues")}


def build_movements(conn) -> dict[str, int]:
    tiers = _league_tiers(conn)
    names = _team_names(conn)
    by_team: dict[int, dict[str, list[tuple[int, int | None]]]] = {}
    for r in conn.execute("SELECT team_id, season, league_id, rank FROM team_league_seasons"):
        by_team.setdefault(r[0], {}).setdefault(r[1], []).append((r[2], r[3]))

    def primary_league(options):
        domestic = [(lid, rank) for lid, rank in options if 1 <= tiers.get(lid, 0) <= 4]
        pool = domestic or options
        return sorted(pool, key=lambda x: (tiers.get(x[0], 9), x[1] or 9999))[0][0]

    conn.execute("DELETE FROM team_movements")
    rows = []
    stats = {"promotion": 0, "relegation": 0, "unknown": 0, "same": 0}
    for team_id, seasons in by_team.items():
        ordered = sorted(seasons, key=lambda s: _season_start(s))
        for a, b in zip(ordered, ordered[1:], strict=False):
            from_lid = primary_league(seasons[a])
            to_lid = primary_league(seasons[b])
            if from_lid == to_lid:
                stats["same"] += 1
                continue
            t_from, t_to = tiers.get(from_lid, 0), tiers.get(to_lid, 0)
            if 1 <= t_to < t_from <= 4:
                direction = "promotion"
            elif 1 <= t_from < t_to <= 4:
                direction = "relegation"
            else:
                direction = "unknown"
            stats[direction] += 1
            rows.append((team_id, a, b, from_lid, to_lid, direction, names.get(team_id)))
    conn.executemany(
        """INSERT OR REPLACE INTO team_movements
           (team_id,season_from,season_to,from_league_id,to_league_id,direction,team_name)
           VALUES (?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return stats


def build_relations(conn) -> int:
    groups: dict[tuple, list[str]] = {}
    meta: dict[tuple, tuple[str, str]] = {}
    for r in conn.execute(
        """SELECT from_league_id, to_league_id, direction, season_from, season_to, team_name
           FROM team_movements WHERE direction IN ('promotion','relegation')"""
    ):
        key = (r[0], r[1], r[2], r[3], r[4])
        groups.setdefault(key, []).append(r[5] or str(r[0]))
        meta[key] = (r[3], r[4])
    conn.execute("DELETE FROM league_relations")
    rows = []
    for (from_lid, to_lid, direction, season_from, season_to), teams in groups.items():
        rows.append(
            (
                from_lid,
                to_lid,
                direction,
                season_from,
                season_to,
                len(teams),
                json.dumps(teams[:10], ensure_ascii=False),
                "inferred",
                0.9,
            )
        )
    conn.executemany(
        """INSERT OR REPLACE INTO league_relations
           (from_league_id,to_league_id,direction,season_from,season_to,
            team_count,sample_teams_json,source,confidence)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)
