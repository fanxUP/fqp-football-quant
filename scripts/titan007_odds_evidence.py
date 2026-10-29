"""Build checked sparse time evidence offline; import into the existing history store."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.titan007_history import canonical

VERSION = "titan007-odds-evidence/v1"
SITE = ZoneInfo("Asia/Shanghai")
FIELDS = ("company_id", "odds_type", "source", "seq", "change_time", "home", "line", "away")
COLUMNS = (
    "batch_id",
    "source_record_key",
    "source_match_id",
    "expected_value",
    "change_at",
    "time_basis",
    "effective_kickoff_at",
    "kickoff_basis",
    "source_url",
    "response_sha256",
    "observed_at",
    "provenance",
)


def _time(value):
    at = datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError("explicit timezone required")
    return at.astimezone(UTC)


def _context_group(history, kickoff):
    """Specific 2022 finals evidence, never a general widening of the window."""
    start = datetime(2022, 4, 1, tzinfo=SITE)
    values, anchors = [], []
    ordered = sorted(history, key=lambda r: r["seq"])
    if [r["seq"] for r in ordered] != list(range(1, len(ordered) + 1)):
        raise ValueError("invalid event group sequence")
    for row in ordered:
        at = datetime.strptime("2022-" + row["change_time_raw"], "%Y-%m-%d %H:%M").replace(
            tzinfo=SITE
        )
        if not start <= at <= kickoff + timedelta(hours=12):
            raise ValueError("outside verified event context")
        values.append(at)
        if kickoff - timedelta(days=180) <= at <= kickoff + timedelta(hours=12):
            anchors.append(at)
    directions = {(a > b) - (a < b) for a, b in zip(values, values[1:], strict=False) if a != b}
    if not anchors or len(directions) > 1:
        raise ValueError("event inference requires consistent order and an existing-window anchor")
    return {
        "event_start": start.isoformat(),
        "anchor_at": max(anchors).isoformat(),
        "event_url": "https://publications.fifa.com/en/annual-report-2021/looking-ahead/",
        "event_id": "fifa-world-cup-2022",
        "group_records": len(ordered),
    }


def build_package(verification_path, batch_content_sha256, *, official_schedules=None, batch_id=1):
    from scripts.sources.titan007.odds import parse_1x2d, parse_1x2d_time

    path = Path(verification_path)
    audit = json.loads(path.read_text())
    if not audit.get("finished_at"):
        raise ValueError("verification is incomplete")
    official_schedules = official_schedules or {}
    matches = {m["match_id"]: m for m in audit["matches"]}
    targets = defaultdict(list)
    for row in audit["rows"]:
        targets[row["match_id"]].append(row)
    result = []
    for mid, rows in targets.items():
        match = matches[mid]
        payload = (path.parent / f"{int(mid)}.js").read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != match["payload_sha256"]:
            raise ValueError("source payload checksum mismatch")
        source = parse_1x2d(payload.decode("utf-8-sig"))
        meta = source["meta"]
        if (meta.get("ScheduleID"), meta.get("hometeamID"), meta.get("guestteamID")) != (
            str(mid),
            str(match["home_id"]),
            str(match["away_id"]),
        ):
            raise ValueError("source identity mismatch")
        kickoff = datetime.fromisoformat(parse_1x2d_time(meta["MatchTime"])).replace(tzinfo=UTC)
        original = datetime.fromisoformat(match["kickoff"]).replace(tzinfo=SITE)
        official = official_schedules.get(str(mid))
        if kickoff != original and (not official or _time(official["kickoff_at"]) != kickoff):
            raise ValueError("changed kickoff needs matching official evidence")
        by_key = {(r["company_id"], r["seq"]): r for r in source["history"]}
        if len(by_key) != len(source["history"]):
            raise ValueError("duplicate source sequence")
        context = {}
        for row in rows:
            found = by_key.get((row["company_id"], row["seq"]))
            if not found or row["source"] != "1x2d" or row["odds_type"] != "europe":
                raise ValueError("source row not found")
            if (found["change_time_raw"], found["home"], float(found["line"]), found["away"]) != (
                row["change_time"],
                row["home"],
                float(row["line"]),
                row["away"],
            ):
                raise ValueError("source content mismatch")
            provenance = {
                "version": VERSION,
                "home_team_id": match["home_id"],
                "away_team_id": match["away_id"],
                "source_matchtime_raw": meta["MatchTime"],
            }
            if found["source_year_raw"]:
                at = datetime.strptime(found["change_time"], "%Y-%m-%d %H:%M").replace(tzinfo=SITE)
                basis = "source_full"
                provenance["source_year"] = found["source_year_raw"]
            else:
                if meta.get("season") != "2022" or meta.get("sclassId") != "75":
                    raise ValueError("unsupported event inference")
                cid = row["company_id"]
                if cid not in context:
                    context[cid] = _context_group(
                        [r for r in source["history"] if r["company_id"] == cid], kickoff
                    )
                provenance.update(context[cid])
                at = datetime.strptime("2022-" + row["change_time"], "%Y-%m-%d %H:%M").replace(
                    tzinfo=SITE
                )
                basis = "inferred_year"
            if official:
                provenance["official_url"] = official["url"]
            result.append(
                {
                    "batch_id": batch_id,
                    "source_record_key": canonical(
                        [mid, row["company_id"], row["odds_type"], row["source"], row["seq"]]
                    ),
                    "source_match_id": mid,
                    "expected_value": {k: row[k] for k in FIELDS},
                    "change_at": at.astimezone(UTC).isoformat(),
                    "time_basis": basis,
                    "effective_kickoff_at": kickoff.isoformat(),
                    "kickoff_basis": "source_and_official" if official else "source_schedule",
                    "source_url": f"https://1x2d.titan007.com/{mid}.js",
                    "response_sha256": digest,
                    "observed_at": _time(match["fetched_file_mtime"]).isoformat(),
                    "provenance": provenance,
                }
            )
    if len({(r["batch_id"], r["source_record_key"]) for r in result}) != len(result):
        raise ValueError("duplicate evidence targets")
    return {
        "version": VERSION,
        "batch_content_sha256": batch_content_sha256,
        "counts": dict(Counter(r["time_basis"] for r in result)),
        "rows": result,
    }


def import_package(conn, package, *, dry_run=True, verify=None):
    """The caller supplies the existing DB connection; no external calls or raw updates."""
    from psycopg2.extras import Json, RealDictCursor, execute_values

    def protected_counts(cur):
        cur.execute(
            "select relid,relname,n_tup_ins,n_tup_upd,n_tup_del from pg_stat_xact_user_tables "
            "where relname=any(%s)",
            (
                [
                    "football_history_batches",
                    "football_history_matches",
                    "football_history_records",
                    "official_matches",
                    "official_results",
                    "match_feature_snapshots",
                    "match_lineup_snapshots",
                    "player_availability_snapshots",
                ],
            ),
        )
        return {r["relid"]: dict(r) for r in cur.fetchall()}

    if package["version"] != VERSION or not package["rows"]:
        raise ValueError("invalid time evidence package")
    if dict(Counter(r["time_basis"] for r in package["rows"])) != package["counts"]:
        raise ValueError("time evidence count mismatch")
    if len({(r["batch_id"], r["source_record_key"]) for r in package["rows"]}) != len(
        package["rows"]
    ):
        raise ValueError("duplicate time evidence targets")
    expected = []
    for row in package["rows"]:
        value = dict(row)
        for k in ("change_at", "effective_kickoff_at", "observed_at"):
            value[k] = _time(value[k])
        expected.append(value)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("set local lock_timeout='2s'")
            cur.execute("set local statement_timeout='90s'")
            cur.execute("select pg_advisory_xact_lock(626292612200)")
            before_writes = protected_counts(cur)
            for bid in {r["batch_id"] for r in expected}:
                cur.execute(
                    "select content_sha256,state,source_name from football_history_batches where id=%s",
                    (bid,),
                )
                batch = cur.fetchone()
                if not batch or tuple(batch.values()) != (
                    package["batch_content_sha256"],
                    "published",
                    "titan007",
                ):
                    raise ValueError("published batch identity mismatch")
            values = [
                tuple(
                    Json(r[k]) if k in ("expected_value", "provenance") else r[k] for k in COLUMNS
                )
                for r in expected
            ]
            execute_values(
                cur,
                "insert into football_history_odds_time_evidence("
                + ",".join(COLUMNS)
                + ") values %s on conflict(batch_id,source_record_key) do nothing",
                values,
                page_size=100,
            )
            for bid in {r["batch_id"] for r in expected}:
                keys = [r["source_record_key"] for r in expected if r["batch_id"] == bid]
                cur.execute(
                    "select "
                    + ",".join(COLUMNS)
                    + " from football_history_odds_time_evidence where batch_id=%s and source_record_key=any(%s)",
                    (bid, keys),
                )
                actual = {r["source_record_key"]: dict(r) for r in cur.fetchall()}
                if any(
                    actual.get(r["source_record_key"]) != r
                    for r in expected
                    if r["batch_id"] == bid
                ):
                    raise ValueError("existing time evidence differs from package")
            if verify is not None:
                verify(cur)
            protected_writes = [
                {
                    "relname": r["relname"],
                    **{
                        k: r[k] - before_writes.get(oid, {}).get(k, 0)
                        for k in ("n_tup_ins", "n_tup_upd", "n_tup_del")
                    },
                }
                for oid, r in protected_counts(cur).items()
            ]
            if any(r["n_tup_ins"] + r["n_tup_upd"] + r["n_tup_del"] for r in protected_writes):
                raise ValueError(
                    "unexpected writes outside time evidence: " + canonical(protected_writes)
                )
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        "status": "dry_run" if dry_run else "verified",
        "records": len(expected),
        "counts": package["counts"],
        "own_protected_writes": protected_writes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--batch-content-sha256", required=True)
    parser.add_argument("--official-schedules", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = build_package(
        args.verification,
        args.batch_content_sha256,
        official_schedules=json.loads(args.official_schedules.read_text()),
    )
    args.output.write_text(canonical(package) + "\n")
    print(json.dumps({"records": len(package["rows"]), "counts": package["counts"]}))


if __name__ == "__main__":
    main()
