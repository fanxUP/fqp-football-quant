"""Backfill append-only Sporttery fixed-bonus odds history.

The Sporttery uniform ``getFixedBonusV1.qry`` response is the authoritative
source for per-match SP changes.  Unlike the live match list, it retains the
published update time for each play, so historical matches can render a real
trend instead of a synthetic interpolation.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Keep this job executable both through ``python -m`` and the repository's
# established direct-script convention used by local cron/launchd jobs.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.backend.src.db import get_db
from scripts.official_storage import store_odds_snapshots
from scripts.sporttery_client import SportteryClient


HAFU_OPTIONS = {
    "hh": ("33", "胜胜"), "hd": ("31", "胜平"), "ha": ("30", "胜负"),
    "dh": ("13", "平胜"), "dd": ("11", "平平"), "da": ("10", "平负"),
    "ah": ("03", "负胜"), "ad": ("01", "负平"), "aa": ("00", "负负"),
}


def _snapshot_time(entry: dict[str, Any]) -> str | None:
    """Return an official update timestamp, or ``None`` when it is malformed."""
    update_date = entry.get("updateDate")
    update_time = entry.get("updateTime")
    if not isinstance(update_date, str) or not isinstance(update_time, str):
        return None
    try:
        return datetime.fromisoformat(f"{update_date}T{update_time}").isoformat()
    except ValueError:
        return None


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _handicap(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _base_snapshot(
    *, entry: dict[str, Any], history_type: str, snapshot_time: str, play_type: str,
    option_code: str, option_name: str, sp_value: float, handicap: float | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_time": snapshot_time,
        "snapshot_label": f"official_history:{history_type}:{option_code}",
        "minutes_before_stop": None,
        "play_type": play_type,
        "option_code": option_code,
        "option_name": option_name,
        "sp_value": sp_value,
        "handicap": handicap,
        "is_open": True,
        "is_single_allowed": False,
        "raw_json": {
            "source_name": "sporttery",
            "source_endpoint": "getFixedBonusV1.qry",
            "history_type": history_type,
            "entry": entry,
        },
    }


def parse_fixed_bonus_history(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize all timestamped official SP values from a fixed-bonus response."""
    history = raw.get("value", {}).get("oddsHistory", {})
    if not isinstance(history, dict):
        return []

    snapshots: list[dict[str, Any]] = []

    def parse_1x2(history_type: str, play_type: str, labels: dict[str, str]) -> None:
        for entry in history.get(history_type, []) or []:
            if not isinstance(entry, dict) or not (at := _snapshot_time(entry)):
                continue
            handicap = _handicap(entry.get("goalLine"))
            for code, name in labels.items():
                if (sp := _positive_float(entry.get(code))) is not None:
                    snapshots.append(_base_snapshot(
                        entry=entry, history_type=history_type, snapshot_time=at,
                        play_type=play_type, option_code=code, option_name=name,
                        sp_value=sp, handicap=handicap,
                    ))

    parse_1x2("hadList", "spf", {"h": "主胜", "d": "平", "a": "客胜"})
    parse_1x2("hhadList", "rqspf", {"h": "让球主胜", "d": "让球平", "a": "让球客胜"})

    for entry in history.get("ttgList", []) or []:
        if not isinstance(entry, dict) or not (at := _snapshot_time(entry)):
            continue
        for goals in range(8):
            if (sp := _positive_float(entry.get(f"s{goals}"))) is not None:
                snapshots.append(_base_snapshot(
                    entry=entry, history_type="ttgList", snapshot_time=at, play_type="zjq",
                    option_code=str(goals), option_name="7+" if goals == 7 else f"{goals}球",
                    sp_value=sp,
                ))

    for entry in history.get("hafuList", []) or []:
        if not isinstance(entry, dict) or not (at := _snapshot_time(entry)):
            continue
        for source_code, (option_code, option_name) in HAFU_OPTIONS.items():
            if (sp := _positive_float(entry.get(source_code))) is not None:
                snapshots.append(_base_snapshot(
                    entry=entry, history_type="hafuList", snapshot_time=at, play_type="bqc",
                    option_code=option_code, option_name=option_name, sp_value=sp,
                ))

    for entry in history.get("crsList", []) or []:
        if not isinstance(entry, dict) or not (at := _snapshot_time(entry)):
            continue
        for source_code, value in entry.items():
            if source_code.endswith("f"):
                continue
            if source_code in {"s-1sh", "s-1sd", "s-1sa"}:
                option_code = {"s-1sh": "other_h", "s-1sd": "other_d", "s-1sa": "other_a"}[source_code]
                option_name = {"other_h": "胜其他", "other_d": "平其他", "other_a": "负其他"}[option_code]
            elif len(source_code) == 6 and source_code.startswith("s") and source_code[3] == "s":
                try:
                    option_code = f"{int(source_code[1:3])}:{int(source_code[4:6])}"
                except ValueError:
                    continue
                option_name = option_code
            else:
                continue
            if (sp := _positive_float(value)) is not None:
                snapshots.append(_base_snapshot(
                    entry=entry, history_type="crsList", snapshot_time=at, play_type="bf",
                    option_code=option_code, option_name=option_name, sp_value=sp,
                ))

    return snapshots


def _remove_existing_snapshots(conn: Any, match_id: int, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep a rerun resumable without replacing or duplicating snapshot rows."""
    if not snapshots:
        return []
    times = sorted({snapshot["snapshot_time"] for snapshot in snapshots})
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT snapshot_time, play_type, option_code, sp_value, COALESCE(handicap, 9999)
            FROM official_odds_snapshots
            WHERE match_id = %s AND snapshot_time = ANY(%s::timestamp[])
            """,
            (match_id, times),
        )
        existing = {
            (row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]), row[1], row[2], float(row[3]), float(row[4]))
            for row in cur.fetchall()
        }
    return [
        snapshot for snapshot in snapshots
        if (
            snapshot["snapshot_time"], snapshot["play_type"], snapshot["option_code"],
            float(snapshot["sp_value"]), snapshot["handicap"] if snapshot["handicap"] is not None else 9999.0,
        ) not in existing
    ]


def store_fixed_bonus_history(conn: Any, match_id: int, raw: dict[str, Any]) -> dict[str, int]:
    """Persist new official historical points for one match without overwriting rows."""
    snapshots = parse_fixed_bonus_history(raw)
    new_snapshots = _remove_existing_snapshots(conn, match_id, snapshots)
    if not new_snapshots:
        return {"inserted": 0, "already_present": len(snapshots), "errors": 0}
    result = store_odds_snapshots(conn, match_id, None, new_snapshots)
    return {
        "inserted": result["inserted"],
        "already_present": len(snapshots) - len(new_snapshots),
        "errors": len(result["errors"]),
    }


def backfill_fixed_bonus_history(
    start_date: str,
    end_date: str,
    limit: int | None = None,
    include_existing: bool = False,
) -> dict[str, Any]:
    """Fetch and persist official SP history for each Sporttery match in a date range."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id, m.source_match_id
                FROM official_matches m
                WHERE m.business_date BETWEEN %s::date AND %s::date
                  AND m.source_match_id IS NOT NULL
                  AND (%s OR NOT EXISTS (
                      SELECT 1 FROM official_odds_snapshots oos
                      WHERE oos.match_id = m.id
                        AND oos.raw_json->>'source_endpoint' = 'getFixedBonusV1.qry'
                  ))
                ORDER BY m.business_date, m.id
                """ + (" LIMIT %s" if limit is not None else ""),
                (start_date, end_date, include_existing, limit)
                if limit is not None
                else (start_date, end_date, include_existing),
            )
            matches = cur.fetchall()

    client = SportteryClient()
    processed = inserted = skipped_existing = failed = 0
    consecutive_forbidden = 0
    source_blocked = False
    try:
        for match_id, source_match_id in matches:
            processed += 1
            try:
                raw = client.get_uniform_fixed_bonus(int(source_match_id))
                with get_db() as conn:
                    result = store_fixed_bonus_history(conn, match_id, raw)
                    inserted += result["inserted"]
                    skipped_existing += result["already_present"]
                    if result["errors"]:
                        failed += 1
                consecutive_forbidden = 0
            except Exception as exc:  # Continue so a single retired fixture cannot stop a season backfill.
                failed += 1
                print(f"[official_odds_history] match_id={match_id} failed: {exc}")
                if "403" in str(exc):
                    consecutive_forbidden += 1
                    if consecutive_forbidden >= 3:
                        source_blocked = True
                        print("[official_odds_history] stopping after 3 consecutive Sporttery 403 responses")
                        break
                else:
                    consecutive_forbidden = 0
    finally:
        client.close()

    return {
        "status": "blocked" if source_blocked else ("ok" if failed == 0 else "partial"),
        "matches_processed": processed,
        "snapshots_inserted": inserted,
        "snapshots_already_present": skipped_existing,
        "matches_failed": failed,
        "source_blocked": source_blocked,
    }


def _season_start(today: date) -> date:
    return date(today.year if today.month >= 7 else today.year - 1, 7, 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill official Sporttery fixed-bonus odds history")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-existing", action="store_true")
    args = parser.parse_args()
    start = args.start_date or _season_start(date.today()).isoformat()
    print(backfill_fixed_bonus_history(start, args.end_date, args.limit, args.include_existing))
