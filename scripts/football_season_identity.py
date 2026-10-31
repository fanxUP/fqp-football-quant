"""Evidence-backed season import; preview is offline, caller owns transactions.

python -m scripts.football_season_identity --input material.json [--mode rehearse|apply]
No fetching, date-based membership inference, model activation or legacy repair.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import psycopg2
from psycopg2.extras import Json, RealDictCursor

_PATH = "/gateway/uniform/football/league/getMatchResultV1.qry"
_SOURCE = "sporttery"
_SYSTEM = "uniform.leagueId+seasonId"
_MAX_MEMBERS = 500


def _identifier(value) -> str:
    text = str(value)
    if not re.fullmatch(r"[1-9][0-9]{0,15}", text):
        raise ValueError("Expected a positive source identifier")
    return text


def _document(doc: dict) -> tuple[dict, dict, tuple[str, str]]:
    try:
        body = doc["body"]
        if not isinstance(body, str) or len(body.encode()) > 8_000_000:
            raise ValueError("Invalid source body size")
        if hashlib.sha256(body.encode()).hexdigest() != doc["sha256"]:
            raise ValueError("Source body SHA-256 mismatch")
        url = urlsplit(doc["url"])
        if (
            url.scheme != "https"
            or url.netloc != "webapi.sporttery.cn"
            or url.path != _PATH
            or url.fragment
        ):
            raise ValueError("Unsupported official season endpoint")
        query = parse_qs(url.query, keep_blank_values=True)
        if any(len(query.get(k, [])) != 1 for k in ("uniformLeagueId", "seasonId")):
            raise ValueError("Missing or repeated source namespace")
        key = tuple(_identifier(query[k][0]) for k in ("uniformLeagueId", "seasonId"))
        captured = datetime.fromisoformat(doc["captured_at"])
        if captured.tzinfo is None:
            raise ValueError("Source capture time requires timezone")
        payload = json.loads(body)
        if payload.get("success") is not True or str(payload.get("errorCode")) != "0":
            raise ValueError("Official response is not successful")
        value = payload["value"]
        for field, expected in zip(("uniformLeagueId", "seasonId"), key, strict=True):
            if field in value and _identifier(value[field]) != expected:
                raise ValueError("Response/query season namespace mismatch")
        evidence = dict(
            url=doc["url"],
            sha256=doc["sha256"],
            captured_at=captured.isoformat(),
            historical_prematch_eligible=False,
            response_id_echo={field: value.get(field) for field in ("uniformLeagueId", "seasonId")},
            binding_basis="response_echo"
            if all(field in value for field in ("uniformLeagueId", "seasonId"))
            else "request_parameters_only",
        )
        return value, evidence, (key[0], key[1])
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Malformed official season material") from exc


def prepare_import(material: dict) -> dict:
    """Validate frozen raw responses before any connection or write.

    A URL/hash preserves provenance; it does not independently authenticate the
    publisher. Production material still requires source/mapping review.
    """
    try:
        competition = material["competition_code"]
        code = material["season_code"]
        name = material["season_name"]
        if (
            not isinstance(competition, str)
            or not competition.strip()
            or len(competition) > 64
            or not re.fullmatch(r"[0-9]{4}(?:-[0-9]{4})?", name)
            or not code.endswith(":" + name)
            or len(code) > 32
        ):
            raise ValueError("Use an explicit competition-specific season code and label")
        boundary, evidence, key = _document(material["boundary_document"])
        start = date.fromisoformat(boundary["seasonStartDate"])
        end = date.fromisoformat(boundary["seasonEndDate"])
        if end < start:
            raise ValueError("Inverted planned season dates")
        documents = material.get("member_documents", [])
        members = material.get("members", [])
        if len(documents) > 60 or len(members) > _MAX_MEMBERS:
            raise ValueError("Season import scope exceeds bounded batch")
        proofs: dict[str, dict] = {}
        for doc in documents:
            value, proof, document_key = _document(doc)
            if (
                document_key != key
                or _identifier(value["seasonId"]) != key[1]
                or _identifier(value["uniformLeagueId"]) != key[0]
            ):
                raise ValueError("Member document belongs to another season/competition")
            for group in value.get("matchList", []):
                for row in group.get("subMatchList", []):
                    # Some official league fixtures are not sold as JC.
                    # They do not acquire an invented JC ID in this adapter.
                    if row.get("gmMatchId") in (None, "", 0, "0"):
                        continue
                    mid = _identifier(row["gmMatchId"])
                    proofs.setdefault(mid, dict(**proof, gm_match_id=mid))
        seen_fixtures, seen_source, selected = set(), set(), []
        for item in members:
            fid = int(_identifier(item["fixture_id"]))
            mid = _identifier(item["jc_match_id"])
            if fid in seen_fixtures or mid in seen_source:
                raise ValueError("Duplicate selected fixture/source membership")
            if mid not in proofs:
                raise ValueError("No explicit source season member; dates/names are insufficient")
            seen_fixtures.add(fid)
            seen_source.add(mid)
            selected.append(dict(fixture_id=fid, jc_match_id=mid, evidence=proofs[mid]))
        return dict(
            competition_code=competition,
            season_code=code,
            season_name=name,
            source_competition_id=key[0],
            source_season_id=key[1],
            planned_start_date=start.isoformat(),
            planned_end_date=end.isoformat(),
            source_timezone="Asia/Shanghai",
            evidence=evidence,
            members=selected,
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Malformed season import") from exc


def import_season(conn, material: dict) -> dict:
    """Append verified links. No commit/rollback; failures belong to caller.

    Call on an otherwise idle transaction. The lock serializes this operator;
    FK/unique/immutable constraints protect direct database writes as well.
    """
    if conn.autocommit:
        raise ValueError("Season import requires a caller-owned transaction, not autocommit")
    plan = prepare_import(material)
    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout='2s'")
        cur.execute("SET LOCAL statement_timeout='8s'")
        cur.execute("SELECT pg_try_advisory_xact_lock(939118,127)")
        if not cur.fetchone()[0]:
            raise ValueError("Season identity importer is busy; no automatic retry")
        cur.execute(
            "SELECT id FROM competitions WHERE competition_code=%s", (plan["competition_code"],)
        )
        found = cur.fetchone()
        if found is None:
            raise ValueError("Canonical competition must already exist")
        cid = found[0]
        cur.execute(
            "SELECT id,season_name FROM seasons WHERE season_code=%s", (plan["season_code"],)
        )
        found = cur.fetchone()
        if found is not None and found[1] != plan["season_name"]:
            raise ValueError("Canonical season label conflicts; do not rewrite the legacy row")
        if found is None:
            # Authoritative dates live on the competition/source relationship.
            # Do not fabricate shared global dates or change legacy rows.
            cur.execute(
                "INSERT INTO seasons(season_code,season_name,is_current) VALUES (%s,%s,false) RETURNING id",
                (plan["season_code"], plan["season_name"]),
            )
            found = cur.fetchone()
        sid = found[0]
        cur.execute(
            "SELECT 1 FROM competition_seasons WHERE season_id=%s AND competition_id<>%s LIMIT 1",
            (sid, cid),
        )
        if cur.fetchone() is not None:
            raise ValueError("Competition-specific season is already shared by another competition")
        cur.execute(
            "INSERT INTO competition_seasons(competition_id,season_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (cid, sid),
        )
        cur.execute(
            "SELECT id FROM competition_seasons WHERE competition_id=%s AND season_id=%s",
            (cid, sid),
        )
        csid = cur.fetchone()[0]
        params = (_SOURCE, _SYSTEM, plan["source_competition_id"], plan["source_season_id"])
        cur.execute(
            "SELECT id,competition_season_id,planned_start_date,planned_end_date,source_timezone FROM football_competition_season_sources WHERE source_name=%s AND id_system=%s AND source_competition_id=%s AND source_season_id=%s",
            params,
        )
        existing = cur.fetchone()
        created_season_source = existing is None
        expected = (
            csid,
            date.fromisoformat(plan["planned_start_date"]),
            date.fromisoformat(plan["planned_end_date"]),
            plan["source_timezone"],
        )
        if existing is not None:
            if existing[1:] != expected:
                raise ValueError("Source season binding or planned dates conflict")
            source_id = existing[0]
        else:
            cur.execute(
                "INSERT INTO football_competition_season_sources(competition_season_id,source_name,id_system,source_competition_id,source_season_id,planned_start_date,planned_end_date,source_timezone,evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (csid, *params, *expected[1:], Json(plan["evidence"])),
            )
            source_id = cur.fetchone()[0]
        added = 0
        for member in plan["members"]:
            fid, mid = member["fixture_id"], member["jc_match_id"]
            cur.execute(
                "SELECT fixture_id FROM football_fixture_source_links WHERE source_name=%s AND id_system='jc.matchId' AND source_match_id=%s",
                (_SOURCE, mid),
            )
            if cur.fetchone() != (fid,):
                raise ValueError("Selected JC source does not identify the existing shared fixture")
            cur.execute(
                "SELECT season_source_id,source_name,match_id_system,source_match_id FROM football_fixture_seasons WHERE fixture_id=%s",
                (fid,),
            )
            previous = cur.fetchone()
            if previous is not None:
                if previous != (source_id, _SOURCE, "jc.matchId", mid):
                    raise ValueError("Fixture already has a conflicting season membership")
                continue
            cur.execute(
                "INSERT INTO football_fixture_seasons(fixture_id,season_source_id,source_name,match_id_system,source_match_id,evidence) VALUES (%s,%s,%s,'jc.matchId',%s,%s)",
                (fid, source_id, _SOURCE, mid, Json(member["evidence"])),
            )
            added += 1
    return dict(
        competition_season_id=csid,
        season_source_id=source_id,
        new_season_sources=int(created_season_source),
        new_memberships=added,
        selected_memberships=len(plan["members"]),
    )


def read_fixture_seasons(conn, fixture_ids: list[int]) -> list[dict]:
    """One bounded read of explicit memberships, no inference from legacy data."""
    if not 1 <= len(fixture_ids) <= _MAX_MEMBERS or any(
        type(fid) is not int or fid <= 0 for fid in fixture_ids
    ):
        raise ValueError("Expected 1..500 positive fixture IDs")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM football_fixture_season_catalog WHERE fixture_id=ANY(%s) ORDER BY fixture_id",
            (fixture_ids,),
        )
        return [dict(row) for row in cur.fetchall()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--mode", choices=("preview", "rehearse", "apply"), default="preview")
    args = parser.parse_args(argv)
    material = json.loads(args.input.read_text())
    plan = prepare_import(material)
    if args.mode == "preview":
        print(
            json.dumps(
                dict(mode="offline_preview", database_access=False, plan=plan), ensure_ascii=False
            )
        )
        return 0
    # The explicit modes use the caller-configured DSN. Do not log credentials.
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        result = import_season(conn, material)
        observed = (
            read_fixture_seasons(conn, [m["fixture_id"] for m in plan["members"]])
            if plan["members"]
            else []
        )
        if len(observed) != len(plan["members"]):
            raise ValueError("Read-after-write season membership count mismatch")
        if args.mode == "apply":
            conn.commit()
        else:
            conn.rollback()
        print(
            json.dumps(
                dict(mode=args.mode, committed=args.mode == "apply", result=result),
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
