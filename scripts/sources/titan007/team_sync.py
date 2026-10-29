"""球队目录梳理：竞彩名称、队徽、球员归属。"""

from __future__ import annotations

from datetime import datetime

from . import assets as assets_mod
from . import store
from . import teams as teams_parser
from .client import AcquisitionStopped, record_operation_failure

TEAM_JS_URL = "https://info.titan007.com/jsData/teamInfo/teamDetail/tdl{team_id}.js"


def build_catalog(conn) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM team_catalog")
    rows = conn.execute(
        """SELECT tm.titan_team_id, tm.lottery_team_id, tm.titan_name,
                  t.full_name lottery_name
           FROM team_mapping tm
           LEFT JOIN lottery_teams t ON t.lottery_team_id=tm.lottery_team_id
           WHERE tm.status='mapped' AND tm.titan_team_id IS NOT NULL
           ORDER BY tm.titan_team_id"""
    ).fetchall()
    payload = []
    for r in rows:
        tid = r["titan_team_id"]
        jc_matches = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE home_id=? OR away_id=?", (tid, tid)
        ).fetchone()[0]
        lineup_players = conn.execute(
            """SELECT COUNT(DISTINCT l.player_id) FROM lineups l
               JOIN matches m ON m.match_id=l.match_id
               WHERE m.home_id=? OR m.away_id=?""",
            (tid, tid),
        ).fetchone()[0]
        squad_players = conn.execute(
            "SELECT COUNT(*) FROM team_squad WHERE team_id=?", (tid,)
        ).fetchone()[0]
        logo = conn.execute(
            """SELECT path FROM assets WHERE asset_type='team_logo'
               AND entity_id=? AND status='ok' LIMIT 1""",
            (tid,),
        ).fetchone()
        payload.append(
            (
                tid,
                r["lottery_team_id"],
                r["lottery_name"] or r["titan_name"],
                r["titan_name"],
                logo[0] if logo else None,
                jc_matches,
                lineup_players,
                squad_players,
                now,
            )
        )
    conn.executemany(
        """INSERT OR REPLACE INTO team_catalog
           (titan_team_id,lottery_team_id,display_name,titan_name,logo_path,
            jc_matches,lineup_players,squad_players,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        payload,
    )
    conn.commit()
    return {
        "teams": len(payload),
        "with_logo": sum(1 for p in payload if p[4]),
        "with_lineups": sum(1 for p in payload if p[6]),
        "with_squad": sum(1 for p in payload if p[7]),
    }


def download_missing_logos(
    conn, client, limit: int | None = None, *, out_dir: str = "data/images/teams"
) -> dict:
    rows = conn.execute(
        """SELECT tm.titan_team_id, t.full_name lottery_name
           FROM team_mapping tm LEFT JOIN lottery_teams t ON t.lottery_team_id=tm.lottery_team_id
           WHERE tm.status='mapped' AND tm.titan_team_id IS NOT NULL
             AND NOT EXISTS(SELECT 1 FROM assets a WHERE a.asset_type='team_logo'
                            AND a.entity_id=tm.titan_team_id AND a.status IN ('ok','missing'))
           ORDER BY tm.titan_team_id"""
    ).fetchall()
    if limit:
        rows = rows[:limit]
    ok = missing = fail = 0
    for i, r in enumerate(rows, 1):
        tid = r["titan_team_id"]
        try:
            row = conn.execute(
                "SELECT logo,name FROM league_teams WHERE team_id=? AND logo IS NOT NULL LIMIT 1",
                (tid,),
            ).fetchone()
            logo = row["logo"] if row else None
            name = row["name"] if row else r["lottery_name"]
            if not logo:
                text = client.get(
                    TEAM_JS_URL.format(team_id=tid), referer="https://info.titan007.com/"
                )
                profile = (
                    teams_parser.normalize_team(teams_parser.parse_team_js(text)).get("profile")
                    or {}
                )
                logo = profile.get("logo")
                name = profile.get("name") or name
            url = assets_mod.team_logo_url(logo)
            if not url:
                missing += 1
                store.upsert_assets(
                    conn,
                    [
                        {
                            "asset_type": "team_logo",
                            "entity_id": tid,
                            "name": name,
                            "url": None,
                            "path": None,
                            "bytes": None,
                            "status": "missing",
                            "fetched_at": datetime.now().isoformat(timespec="seconds"),
                        }
                    ],
                )
            else:
                path, size, _ = assets_mod.download_image(client, url, out_dir, tid)
                store.upsert_assets(
                    conn,
                    [
                        {
                            "asset_type": "team_logo",
                            "entity_id": tid,
                            "name": name,
                            "url": url,
                            "path": path,
                            "bytes": size,
                            "status": "ok",
                            "fetched_at": datetime.now().isoformat(timespec="seconds"),
                        }
                    ],
                )
                ok += 1
            if i % 25 == 0:
                print(f"[{i}/{len(rows)}] ok={ok} missing={missing} fail={fail}", flush=True)
        except AcquisitionStopped:
            raise
        except Exception as exc:
            record_operation_failure()
            fail += 1
            print(f"[{i}/{len(rows)}] {tid}: skip {exc}", flush=True)
    return {"ok": ok, "missing": missing, "fail": fail, "targets": len(rows)}


def fetch_squads(conn, client, limit: int | None = None) -> dict:
    rows = conn.execute(
        """SELECT tm.titan_team_id, t.full_name lottery_name
           FROM team_mapping tm LEFT JOIN lottery_teams t ON t.lottery_team_id=tm.lottery_team_id
           WHERE tm.status='mapped' AND tm.titan_team_id IS NOT NULL
             AND NOT EXISTS(SELECT 1 FROM team_squad s WHERE s.team_id=tm.titan_team_id)
           ORDER BY tm.titan_team_id"""
    ).fetchall()
    if limit:
        rows = rows[:limit]
    ok = fail = 0
    for i, r in enumerate(rows, 1):
        tid = r["titan_team_id"]
        try:
            text = client.get(TEAM_JS_URL.format(team_id=tid), referer="https://info.titan007.com/")
            data = teams_parser.normalize_team(teams_parser.parse_team_js(text))
            store.save_team(conn, data)
            ok += 1
            if i % 25 == 0:
                print(f"[{i}/{len(rows)}] ok={ok} fail={fail}", flush=True)
        except AcquisitionStopped:
            raise
        except Exception as exc:
            record_operation_failure()
            fail += 1
            print(f"[{i}/{len(rows)}] {tid}: skip {exc}", flush=True)
    return {"ok": ok, "fail": fail, "targets": len(rows)}
