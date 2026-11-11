"""球员转会与球队教练。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from . import jsfmt
from .client import AcquisitionStopped, record_operation_failure

PLAYER_INFO_URL = "https://info.titan007.com/jsData/playerInfo/player{player_id}.js"
TEAM_JS_URL = "https://info.titan007.com/jsData/teamInfo/teamDetail/tdl{team_id}.js"


def parse_transfers(text: str) -> list[dict[str, Any]]:
    rows = jsfmt.extract_js_literal(text, "transferInfo") or []
    out = []
    for r in rows:
        if not isinstance(r, list) or len(r) < 12:
            continue
        out.append(
            {
                "season": r[0],
                "from_team_id": _int(r[1]),
                "to_team_id": _int(r[2]),
                "transfer_date": r[3],
                "end_date": r[4] or None,
                "from_name": r[5],
                "to_name": r[7],
                "from_name_en": r[11] if len(r) > 11 else None,
                "to_name_en": r[12] if len(r) > 12 else None,
                "fee": r[9] or None,
                "flag": _int(r[10]),
            }
        )
    return out


def parse_coach(text: str) -> dict[str, Any]:
    rows = jsfmt.extract_js_literal(text, "coach") or []
    if not rows or not isinstance(rows[0], list):
        return {}
    r = rows[0]
    return {
        "coach_player_id": _int(r[0]) if len(r) > 0 else None,
        "coach_name": r[2] if len(r) > 2 else None,
        "coach_name_en": r[4] if len(r) > 4 else None,
    }


def _int(value):
    try:
        return int(str(value).strip())
    except TypeError, ValueError:
        return None


def sync_coaches(conn, client, team_ids: Iterable[int]) -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    ok = fail = 0
    ids = list(team_ids)
    for i, tid in enumerate(ids, 1):
        try:
            text = client.get(TEAM_JS_URL.format(team_id=tid), referer="https://info.titan007.com/")
            coach = parse_coach(text)
            conn.execute(
                """INSERT INTO team_coaches
                   (team_id,coach_name,coach_player_id,coach_name_en,updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(team_id) DO UPDATE SET
                     coach_name=excluded.coach_name, coach_player_id=excluded.coach_player_id,
                     coach_name_en=excluded.coach_name_en, updated_at=excluded.updated_at""",
                (
                    tid,
                    coach.get("coach_name"),
                    coach.get("coach_player_id"),
                    coach.get("coach_name_en"),
                    now,
                ),
            )
            ok += 1
        except AcquisitionStopped:
            raise
        except Exception as exc:
            record_operation_failure()
            fail += 1
            print(f"[{i}/{len(ids)}] {tid}: skip {exc}", flush=True)
        if i % 50 == 0:
            conn.commit()
            print(f"[coach {i}/{len(ids)}] ok={ok} fail={fail}", flush=True)
    conn.commit()
    return {"ok": ok, "fail": fail}


def sync_transfers(conn, client, player_ids: Iterable[int]) -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    ok = empty = fail = 0
    ids = list(player_ids)
    for i, pid in enumerate(ids, 1):
        try:
            text = client.get(
                PLAYER_INFO_URL.format(player_id=pid), referer="https://info.titan007.com/"
            )
            transfers = parse_transfers(text)
            for t in transfers:
                conn.execute(
                    """INSERT OR REPLACE INTO player_transfers
                       (player_id,season,from_team_id,to_team_id,transfer_date,end_date,
                        from_name,to_name,from_name_en,to_name_en,fee,flag,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        pid,
                        t["season"],
                        t["from_team_id"],
                        t["to_team_id"],
                        t["transfer_date"],
                        t["end_date"],
                        t["from_name"],
                        t["to_name"],
                        t["from_name_en"],
                        t["to_name_en"],
                        t["fee"],
                        t["flag"],
                        now,
                    ),
                )
            conn.execute(
                "INSERT OR REPLACE INTO player_transfer_checked"
                " (player_id,checked_at,status) VALUES (?,?,'ok')",
                (pid, now),
            )
            if transfers:
                ok += 1
            else:
                empty += 1
        except AcquisitionStopped:
            raise
        except Exception as exc:
            record_operation_failure()
            fail += 1
            if "404" in str(exc):
                conn.execute(
                    "INSERT OR REPLACE INTO player_transfer_checked"
                    " (player_id,checked_at,status,missing_reason)"
                    " VALUES (?,?,'no_page','球员页 404')",
                    (pid, now),
                )
            print(f"[{i}/{len(ids)}] {pid}: skip {exc}", flush=True)
        if i % 50 == 0:
            conn.commit()
            print(f"[transfer {i}/{len(ids)}] ok={ok} empty={empty} fail={fail}", flush=True)
    conn.commit()
    return {"ok": ok, "empty": empty, "fail": fail}
