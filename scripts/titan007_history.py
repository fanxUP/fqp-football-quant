"""Offline, classified historical backfill; no network, training or legacy writes.

Export a deterministic compressed package, inspect it, then import it using the
server's loopback database. Missing original acquisition times are permitted.
The package is cleaned source history, not an assertion of past availability.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from itertools import chain, islice
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "titan007-history/v1"
DOMAINS = (
    "match_stats",
    "events",
    "lineups",
    "predicted_lineups",
    "match_injuries",
    "player_transfers",
    "player_stats",
    "player_appearances",
    "odds",
    "odds_history",
)
POSTMATCH = {"match_stats", "events", "lineups", "player_stats", "player_appearances"}
MATCH_COLUMNS = (
    "source_match_id",
    "source_competition_id",
    "source_season",
    "kickoff_at",
    "match_status",
    "source_home_team_id",
    "source_away_team_id",
    "home_name",
    "away_name",
    "home_goals",
    "away_goals",
    "source_updated_at",
    "source_metadata",
)
RECORD_COLUMNS = (
    "domain",
    "source_record_key",
    "source_match_id",
    "source_player_id",
    "side",
    "origin",
    "value_json",
)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while block := f.read(4 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def timestamp(value, *, site_time=False):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
        if dt.tzinfo is None:
            if not site_time:
                return None
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return dt.astimezone(UTC).isoformat()
    except ValueError:
        return None


def day(value):
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        return None


def positive(value):
    return value if type(value) is int and value > 0 else None


def _clean(value):
    if isinstance(value, str):
        return value.replace("\x00", "").strip()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non_finite_number")
    return value


def normalize(domain, row, match, roster_complete=False):
    """Keep reported, predicted and derived values explicitly distinguishable."""
    r = {k: _clean(v) for k, v in row.items() if k != "raw"}
    side = r.get("side") or None
    if side is not None and side not in ("home", "away"):
        raise ValueError("invalid_side")
    if domain in POSTMATCH and match["match_status"] != "finished":
        raise ValueError("not_finished")
    origin = "reported"
    if domain == "match_stats":
        key = r["stat_key"]
        unit = (
            "percent"
            if any("%" in str(r[k] or "") for k in ("home_value", "away_value"))
            else "source_numeric"
        )
        values = []
        for k in ("home_value", "away_value"):
            text = "" if r[k] is None else str(r[k]).strip()
            n = float(text.rstrip("%")) if re.fullmatch(r"\d+(?:\.\d+)?%?", text) else None
            if n is not None and unit == "percent" and n > 100:
                raise ValueError("invalid_percentage")
            values.append(n)
        r.update(
            home_numeric=values[0],
            away_numeric=values[1],
            unit=unit,
            period="extra_time"
            if "加时" in key
            else "first_half"
            if "半场" in key
            else "source_full_match",
        )
    elif domain == "events":
        text = str(r.get("minute") or "")
        minute = re.fullmatch(r"(\d{1,3})(?:\+(\d{1,2}))?['’]?", text)
        r.update(
            minute_base=int(minute[1]) if minute else None,
            minute_added=int(minute[2] or 0) if minute else None,
        )
    elif domain == "lineups":
        if r.get("starter") not in (0, 1):
            raise ValueError("invalid_starter")
        if not r.get("player_name"):
            raise ValueError("missing_player_name")
        r.update(
            roster_complete=roster_complete,
            birth_date=day(r.get("birth")),
            source_acquired_at=None,
            published_at=None,
        )
    elif domain == "predicted_lineups":
        origin = "prediction"
        r.update(
            confirmed=False,
            published_at=None,
            timestamp_note="announced_at was copied from updated_at by the legacy collector; not publication proof",
        )
    elif domain == "match_injuries":
        r.update(
            occurred_date=day(r.get("occurred_at")),
            expected_return_date=day(r.get("expected_return")),
            current_availability=False,
            source_acquired_at=None,
            published_at=None,
        )
    elif domain == "player_transfers":
        r.update(
            effective_date=day(r.get("transfer_date")),
            end_date_normalized=day(r.get("end_date")),
            registration_confirmed=False,
        )
        r["timeline_usable"] = r["effective_date"] is not None
    elif domain == "player_appearances":
        origin = "derived"
        r.update(derivation="legacy-name-substitution/default90-v1", reported_minutes=False)
    elif domain == "player_stats":
        try:
            r["metrics"] = json.loads(r.pop("data_json") or "{}")
        except ValueError, TypeError:
            raise ValueError("invalid_player_metrics") from None
    elif domain in ("odds", "odds_history"):
        origin = "market"
        r["official"] = False
        r["market"] = {"europe": "1x2", "asian": "asian_handicap", "overunder": "total_goals"}.get(
            r["odds_type"], "unknown"
        )
        r["phase"] = "unknown"  # The source field called live does not prove in-play.
        if domain == "odds_history":
            text = str(r.get("change_time") or "")
            r["change_at"] = (
                timestamp(text, site_time=True)
                if re.match(r"^\d{4}-\d{2}-\d{2}[ T]", text)
                else None
            )
            r["timeline_usable"] = r["change_at"] is not None
            r["change_timezone_basis"] = "site_Asia/Shanghai" if r["change_at"] else "unknown"
    return side, origin, r


class CsvPackageWriter:
    def __init__(self, path):
        self.path = path
        self.count = 0
        self.digest = hashlib.sha256()
        self.raw = path.open("wb")
        self.gz = gzip.GzipFile(filename="", fileobj=self.raw, mode="wb", mtime=0, compresslevel=1)
        self.buffer = io.StringIO()
        self.writer = csv.writer(self.buffer, lineterminator="\n")

    def write(self, row):
        self.writer.writerow(row)
        data = self.buffer.getvalue().encode()
        self.buffer.seek(0)
        self.buffer.truncate(0)
        self.digest.update(data)
        self.gz.write(data)
        self.count += 1

    def close(self):
        self.gz.close()
        self.raw.close()
        return {
            "file": self.path.name,
            "rows": self.count,
            "content_sha256": self.digest.hexdigest(),
            "compressed_sha256": sha(self.path),
            "bytes": self.path.stat().st_size,
        }


def load_matches(conn):
    names = {
        (r["league_id"], r["team_id"]): r["name"]
        for r in conn.execute("select * from league_teams")
    }
    league = {r["match_id"]: dict(r) for r in conn.execute("select * from league_results")}
    detailed = {r["match_id"]: dict(r) for r in conn.execute("select * from matches")}
    lottery = defaultdict(list)
    for r in conn.execute("select * from lottery_matches where titan_match_id is not null"):
        lottery[r["titan_match_id"]].append(
            {
                k: r[k]
                for k in (
                    "lottery_match_id",
                    "home_team",
                    "home_full_name",
                    "away_team",
                    "away_full_name",
                )
            }
        )
    result = {}
    rejected = Counter()
    examples = []
    for mid in sorted(league.keys() | detailed.keys()):
        a = detailed.get(mid)
        b = league.get(mid)
        try:
            if a and b:
                if (a["home_id"], a["away_id"]) != (b["home_id"], b["away_id"]):
                    raise ValueError("team_conflict")
                if (
                    positive(a["league_id"])
                    and positive(b["league_id"])
                    and a["league_id"] != b["league_id"]
                ):
                    raise ValueError("competition_conflict")
                if a["status_code"] == b["status"] == -1 and any(
                    a[k] is not None and b[k] is not None and a[k] != b[k]
                    for k in ("home_score", "away_score")
                ):
                    raise ValueError("score_conflict")
                at, bt = (
                    timestamp(a["kickoff"], site_time=True),
                    timestamp(b["match_time"], site_time=True),
                )
                if at and bt and at != bt:
                    raise ValueError("kickoff_conflict")
            r = a or b
            detailed_source = a is not None
            home, away = positive(r["home_id"]), positive(r["away_id"])
            if not positive(mid) or not home or not away or home == away:
                raise ValueError("invalid_identity")
            at = timestamp(r["kickoff"] if detailed_source else r["match_time"], site_time=True)
            if not at:
                raise ValueError("missing_kickoff")
            status = r["status_code"] if detailed_source else r["status"]
            finished = status == -1
            hg, ag = r["home_score"], r["away_score"]
            score_fallback = False
            if a and b and a["status_code"] == b["status"] == -1:
                if hg is None:
                    hg = b["home_score"]
                    score_fallback = True
                if ag is None:
                    ag = b["away_score"]
                    score_fallback = True
            if finished and (type(hg) is not int or type(ag) is not int or hg < 0 or ag < 0):
                raise ValueError("invalid_finished_score")
            league_id = r["league_id"]
            season = (
                _clean(b.get("season"))
                if b and positive(league_id) and league_id == b["league_id"]
                else None
            )
            metadata = {
                "source_tables": [n for n, v in [("matches", a), ("league_results", b)] if v],
                "status_code": status,
                "score_scope": "source_reported_full_match",
                "home_half": r["home_half"],
                "away_half": r["away_half"],
                "lottery_links": lottery.get(mid, []),
                "source_acquired_at": None,
                "published_at": None,
                "score_gap_filled_from_league_results": score_fallback,
                "season_source_table": "league_results" if season else None,
                "source_timestamp_note": "legacy first_fetched_at/result_confirmed_at may be derived from updated_at",
            }
            if a:
                metadata.update(
                    source_updated_text=a.get("updated_at"),
                    source_first_fetched_text=a.get("first_fetched_at"),
                    home_extra=a.get("home_score_et"),
                    away_extra=a.get("away_score_et"),
                    home_penalties=a.get("home_pen"),
                    away_penalties=a.get("away_pen"),
                )
            if b:
                metadata.update(note=b.get("note"), flags_json=b.get("flags_json"))
            result[mid] = {
                "source_match_id": mid,
                "source_competition_id": league_id,
                "source_season": season,
                "kickoff_at": at,
                "match_status": "finished"
                if finished
                else {
                    -14: "postponed",
                    -12: "abandoned",
                    -10: "cancelled",
                    0: "scheduled",
                    1: "live",
                    3: "live",
                }.get(status, "unknown"),
                "source_home_team_id": home,
                "source_away_team_id": away,
                "home_name": a["home_name"] if a else names.get((league_id, home)),
                "away_name": a["away_name"] if a else names.get((league_id, away)),
                "home_goals": hg if type(hg) is int and hg >= 0 else None,
                "away_goals": ag if type(ag) is int and ag >= 0 else None,
                "source_updated_at": timestamp(a.get("updated_at")) if a else None,
                "source_metadata": canonical(metadata),
            }
        except ValueError as exc:
            rejected[str(exc)] += 1
            if len(examples) < 100:
                examples.append({"source_match_id": mid, "reason": str(exc)})
    return result, dict(rejected), examples


def export_package(source, output, progress=print):
    source = Path(source)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    before = source.stat()
    conn = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma query_only=on")
    conn.execute("begin")
    files = []
    counts = {}
    rejects = {}
    try:
        matches, bad, examples = load_matches(conn)
        writer = CsvPackageWriter(output / "matches.csv.gz")
        for row in matches.values():
            writer.write([row[k] for k in MATCH_COLUMNS])
        files.append(writer.close())
        counts["matches"] = len(matches)
        rejects["matches"] = bad
        complete = {
            (r[0], r[1])
            for r in conn.execute(
                "select match_id,side from lineups group by match_id,side having sum(starter)=11 and count(distinct case when starter=1 and player_id>0 then player_id end)=11"
            )
        }
        for domain in DOMAINS:
            columns = conn.execute(f'pragma table_info("{domain}")').fetchall()
            pk = [c["name"] for c in sorted(columns, key=lambda c: c["pk"]) if c["pk"]]
            order = ",".join('"' + k + '"' for k in pk)
            writer = CsvPackageWriter(output / (domain + ".csv.gz"))
            bad = Counter()
            seen = 0
            transfer_keys = set()
            for raw in conn.execute(f'select * from "{domain}" order by {order}'):
                row = dict(raw)
                mid = row.get("match_id")
                seen += 1
                try:
                    if domain != "player_transfers" and mid not in matches:
                        raise ValueError("missing_or_conflicting_match")
                    side, origin, value = normalize(
                        domain, row, matches.get(mid), (mid, row.get("side")) in complete
                    )
                    key = canonical([row[k] for k in pk])
                    if domain == "player_transfers":
                        # SQLite permits duplicates in composite keys containing NULL.
                        if key in transfer_keys:
                            raise ValueError("duplicate_source_transfer_key")
                        transfer_keys.add(key)
                    writer.write(
                        [
                            domain,
                            key,
                            mid,
                            positive(row.get("player_id")),
                            side,
                            origin,
                            canonical(value),
                        ]
                    )
                except ValueError as exc:
                    bad[str(exc)] += 1
            files.append(writer.close())
            counts[domain] = writer.count
            rejects[domain] = dict(bad)
            progress(
                canonical(
                    {
                        "domain": domain,
                        "source_rows": seen,
                        "accepted": writer.count,
                        "rejected": dict(bad),
                    }
                )
            )
        conn.rollback()
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("source changed while exporting")
        content = {
            "version": VERSION,
            "files": [{k: f[k] for k in ("file", "rows", "content_sha256")} for f in files],
        }
        manifest = {
            "version": VERSION,
            "source_name": "titan007",
            "created_at": datetime.now(UTC).isoformat(),
            "content_sha256": hashlib.sha256(canonical(content).encode()).hexdigest(),
            "files": files,
            "counts": counts,
            "rejections": rejects,
            "match_rejection_examples": examples,
            "source_database_bytes": before.st_size,
            "source_acquired_at": None,
            "usage": "Historical reference; original acquisition unknown. No implied past availability or current injury status.",
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        return manifest
    finally:
        conn.close()


class IteratorText(io.TextIOBase):
    def __init__(self, rows):
        self.rows = iter(rows)
        self.pending = ""
        self.lines_read = 0

    def read(self, size=-1):
        if size < 0:
            return self.pending + "".join(self.rows)
        while len(self.pending) < size:
            try:
                self.pending += next(self.rows)
                self.lines_read += 1
            except StopIteration:
                break
        result, self.pending = self.pending[:size], self.pending[size:]
        return result


def _official_match(row, official):
    meta = json.loads(row["source_metadata"])
    ids = []
    for link in meta.get("lottery_links", []):
        candidate = official.get(str(link["lottery_match_id"]))
        if candidate is None:
            continue
        if candidate["home_team_name"] not in (link["home_team"], link["home_full_name"]):
            continue
        if candidate["away_team_name"] not in (link["away_team"], link["away_full_name"]):
            continue
        if timestamp(str(candidate["kickoff_time"]), site_time=True) != row["kickoff_at"]:
            continue
        ids.append(candidate["id"])
    return ids[0] if len(set(ids)) == 1 else None


def import_package(conn, package, *, dry_run=False, progress=print):
    """Caller owns the transaction; failed copies never publish a partial batch."""
    from psycopg2.extras import RealDictCursor

    package = Path(package)
    manifest = json.loads((package / "manifest.json").read_text())
    if manifest["version"] != VERSION or manifest["source_name"] != "titan007":
        raise ValueError("package contract mismatch")
    expected = ["matches.csv.gz", *[d + ".csv.gz" for d in DOMAINS]]
    if [f["file"] for f in manifest["files"]] != expected:
        raise ValueError("package file set mismatch")
    content = {
        "version": VERSION,
        "files": [{k: f[k] for k in ("file", "rows", "content_sha256")} for f in manifest["files"]],
    }
    if hashlib.sha256(canonical(content).encode()).hexdigest() != manifest["content_sha256"]:
        raise ValueError("manifest content mismatch")
    for f in manifest["files"]:
        if sha(package / f["file"]) != f["compressed_sha256"]:
            raise ValueError("package checksum mismatch")
        digest = hashlib.sha256()
        with gzip.open(package / f["file"], "rb") as stream:
            while block := stream.read(4 * 1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != f["content_sha256"]:
            raise ValueError("package content checksum mismatch")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("set local lock_timeout='2s'")
        cur.execute("set local statement_timeout='600s'")
        cur.execute("select pg_try_advisory_xact_lock(626292611900)")
        if not list(cur.fetchone().values())[0]:
            raise ValueError("another historical importer is active")
        cur.execute(
            "select id from football_history_batches where source_name=%s and content_sha256=%s and state=%s",
            ("titan007", manifest["content_sha256"], "published"),
        )
        previous = cur.fetchone()
        if previous:
            return {"status": "unchanged", "batch_id": previous["id"], "counts": manifest["counts"]}
        cur.execute("savepoint history_import")
        cur.execute(
            "insert into football_history_batches(source_name,content_sha256,normalization_version,manifest) values (%s,%s,%s,%s::jsonb) returning id",
            ("titan007", manifest["content_sha256"], VERSION, canonical(manifest)),
        )
        batch = cur.fetchone()["id"]
        cur.execute(
            "select source_team_id,team_id from football_team_source_links where source_name='titan007' and id_system='league_team'"
        )
        teams = {int(r["source_team_id"]): r["team_id"] for r in cur.fetchall()}
        cur.execute(
            "select id,source_match_id,home_team_name,away_team_name,kickoff_time from official_matches"
        )
        official = {r["source_match_id"]: r for r in cur.fetchall()}

        def mapped_matches():
            buffer = io.StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            with gzip.open(package / "matches.csv.gz", "rt", newline="") as f:
                for values in csv.reader(f):
                    row = dict(zip(MATCH_COLUMNS, values, strict=True))
                    writer.writerow(
                        [
                            batch,
                            *values,
                            teams.get(int(row["source_home_team_id"])),
                            teams.get(int(row["source_away_team_id"])),
                            _official_match(row, official),
                        ]
                    )
                    yield buffer.getvalue()
                    buffer.seek(0)
                    buffer.truncate(0)

        columns = ("batch_id", *MATCH_COLUMNS, "home_team_id", "away_team_id", "official_match_id")
        cur.copy_expert(
            "COPY football_history_matches(" + ",".join(columns) + ") FROM STDIN WITH (FORMAT CSV)",
            IteratorText(mapped_matches()),
        )
        cur.execute("select count(*) n from football_history_matches where batch_id=%s", (batch,))
        if cur.fetchone()["n"] != manifest["counts"]["matches"]:
            raise ValueError("match count mismatch")
        progress(
            canonical(
                {
                    "phase": "matches_copied",
                    "batch_id": batch,
                    "rows": manifest["counts"]["matches"],
                }
            )
        )
        for domain in DOMAINS:

            def records(selected_domain=domain):
                with gzip.open(package / (selected_domain + ".csv.gz"), "rt", newline="") as f:
                    # Exported keys/payloads are canonical JSON, so embedded
                    # newlines are escaped. Prefix validated one-line CSV rows
                    # without parsing and serializing millions of JSON fields.
                    for line in f:
                        if not line.startswith(selected_domain + ","):
                            raise ValueError("domain mismatch")
                        yield str(batch) + "," + line

            lines = records()
            copied = 0
            while (first := next(lines, None)) is not None:
                reader = IteratorText(chain((first,), islice(lines, 199999)))
                cur.copy_expert(
                    "COPY football_history_records(batch_id,"
                    + ",".join(RECORD_COLUMNS)
                    + ") FROM STDIN WITH (FORMAT CSV)",
                    reader,
                )
                if cur.rowcount != reader.lines_read:
                    raise ValueError("COPY acknowledgement count mismatch")
                copied += reader.lines_read
                progress(
                    canonical(
                        {
                            "phase": "domain_copy_progress",
                            "batch_id": batch,
                            "domain": domain,
                            "copied_rows": copied,
                        }
                    )
                )
            # PostgreSQL's COPY command tag is the acknowledged inserted row
            # count. Repeated count(*) scans of a fresh, unanalyzed large table
            # can otherwise choose pathological bitmap plans. A separate
            # read-only post-commit audit verifies the published relations.
            if copied != manifest["counts"][domain]:
                raise ValueError("record count mismatch")
            progress(
                canonical(
                    {
                        "phase": "domain_copied",
                        "batch_id": batch,
                        "domain": domain,
                        "rows": manifest["counts"][domain],
                    }
                )
            )
        cur.execute(
            "update football_history_batches set state='published' where id=%s and state='building'",
            (batch,),
        )
        cur.execute(
            "select count(*) n,count(home_team_id) home_links,count(away_team_id) away_links,count(official_match_id) official_links from football_history_matches where batch_id=%s",
            (batch,),
        )
        mapped = dict(cur.fetchone())
        if dry_run:
            cur.execute("rollback to savepoint history_import")
        cur.execute("release savepoint history_import")
        return {
            "status": "dry_run" if dry_run else "published",
            "batch_id": batch,
            "counts": manifest["counts"],
            "identity_coverage": mapped,
            "content_sha256": manifest["content_sha256"],
        }


def _loopback_parameters():
    import psycopg2
    from psycopg2.extensions import parse_dsn

    error = "explicit loopback DATABASE_URL required; indirect routing is not allowed"
    if {"PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"}.intersection(os.environ):
        raise ValueError(error)
    try:
        params = parse_dsn(os.environ.get("DATABASE_URL", ""))
    except psycopg2.Error:
        raise ValueError(error) from None
    if (
        params.get("host") not in ("127.0.0.1", "localhost", "::1")
        or not params.get("dbname")
        or "service" in params
        or ("hostaddr" in params and params["hostaddr"] not in ("127.0.0.1", "::1"))
    ):
        raise ValueError(error)
    # Pin numeric routing so neither DNS nor libpq defaults can redirect writes.
    params["hostaddr"] = "::1" if params["host"] == "::1" else "127.0.0.1"
    params["connect_timeout"] = "5"
    return params


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", type=Path)
    group.add_argument("--import-package", type=Path)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data/sources/titan007/titan007.db",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.export:
        result = export_package(args.source, args.export)
    else:
        import psycopg2

        with psycopg2.connect(**_loopback_parameters()) as conn:
            result = import_package(conn, args.import_package, dry_run=not args.apply)
        conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
