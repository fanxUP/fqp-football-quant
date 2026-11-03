"""Reconcile raw Titan match rows with verified FQP identities and results.

The source SQLite file is opened read-only. A production import requires a
compressed or plain source package, the FQP runtime role, an explicit target
marker, and the command-line write flag. The caller owns the PostgreSQL
transaction; writes are limited to the append-only P136 result-fact table.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from contextlib import closing
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, TypedDict, cast
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import RealDictCursor

from scripts.football_fixture_result_facts import store_result_fact
from scripts.result_status import is_void_official_result

PACKAGE_CONTRACT = "fqp.titan007-result-package/v1"
SOURCE_NAME = "titan007"
ID_SYSTEM = "matchId"
EVIDENCE_CONTRACT = "football-match-result-fact/v1"
OFFICIAL_RULE_URL = "https://www.sporttery.cn/help/2968.html?gid=9"
_OFFICIAL_HOSTS = {"sporttery.cn", "www.sporttery.cn", "m.sporttery.cn", "webapi.sporttery.cn"}
TEAM_NAME_NORMALIZATION = "titan007-cn-explicit-aliases/v2"
_TEAM_NAME_ALIASES = {
    "布莱顿": "布赖顿",
    "狼队": "伍尔弗汉普顿",
    "谢菲尔德联队": "谢菲尔德联",
    "莱斯特城": "莱切斯特城",
}
_SCORE_RE = re.compile(r"^(\d{1,2})\s*[-－–—:：]\s*(\d{1,2})$")
_FULL_DATE_RE = re.compile(
    r"(?:(?P<year>20\d{2})\s*[-/.年]\s*)?"
    r"(?P<month>\d{1,2})\s*[-/.月]\s*"
    r"(?P<day>\d{1,2})\s*日?"
    r"(?:\s*[T ]\s*(?P<hour>\d{1,2}):(?P<minute>\d{2}))?"
)
_DAY_ONLY_RE = re.compile(r"(?P<day>\d{1,2})\s*日(?:\s*(?P<hour>\d{1,2}):(?P<minute>\d{2}))?")
_MATCH_ID_RE = re.compile(r"showgoallist\s*\(\s*(\d{1,16})\s*\)", re.IGNORECASE)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class _TitanRowParser(HTMLParser):
    """Extract the visible text and typed match ID from a single Titan row."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None
        self._onclick_ids: list[str] = []
        self._sid_ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {str(key).lower(): value for key, value in attrs}
        if tag == "tr":
            if self._row is not None:
                raise ValueError("raw_nested_match_row")
            self._row = []
        if self._row is not None and tag == "td":
            self._cell = {"attrs": attributes, "text": []}
            self._row.append(self._cell)
        sid = attributes.get("sid")
        if sid and re.fullmatch(r"\d{1,16}", str(sid).strip()):
            self._sid_ids.append(str(sid).strip())
        onclick = attributes.get("onclick")
        if onclick:
            self._onclick_ids.extend(_MATCH_ID_RE.findall(onclick))

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self._cell = None
        elif tag == "tr":
            if self._row is None:
                raise ValueError("raw_row_structure_invalid")
            self.rows.append(self._row)
            self._row = None


class TitanResultPackage(TypedDict):
    contract: str
    source_database: str
    source_table: str
    requested_ids_sha256: str
    requested_count: int
    record_count: int
    missing_source_ids: list[str]
    records: list[Mapping[str, Any]]


def _plain_text(parts: Iterable[str]) -> str:
    text = unicodedata.normalize("NFC", " ".join(parts))
    return " ".join(text.replace("\u00a0", " ").split())


def _date_value(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("normalized_match_date_missing")
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("normalized_match_date_invalid") from exc
    if parsed.isoformat() != value.strip():
        raise ValueError("normalized_match_date_invalid")
    return parsed


def _kickoff_parts(value: Any) -> tuple[date, str] | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("normalized_kickoff_invalid")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("normalized_kickoff_invalid") from exc
    return parsed.date(), parsed.strftime("%H:%M")


def _check_raw_date(
    text: str, actual_date: date, normalized_kickoff: tuple[date, str] | None
) -> None:
    cleaned = _plain_text([text])
    full = _FULL_DATE_RE.search(cleaned)
    if full and (full.group("month") or full.group("year")):
        month = int(full.group("month"))
        day_value = int(full.group("day"))
        year = int(full.group("year")) if full.group("year") else actual_date.year
        try:
            raw_date = date(year, month, day_value)
        except ValueError as exc:
            raise ValueError("raw_match_date_invalid") from exc
        if raw_date != actual_date:
            raise ValueError("raw_match_date_mismatch")
        raw_time = (
            f"{int(full.group('hour')):02d}:{full.group('minute')}"
            if full.group("hour") is not None
            else None
        )
    else:
        day_only = _DAY_ONLY_RE.search(cleaned)
        if not day_only:
            raise ValueError("raw_match_date_unparseable")
        if int(day_only.group("day")) != actual_date.day:
            raise ValueError("raw_match_date_mismatch")
        raw_time = (
            f"{int(day_only.group('hour')):02d}:{day_only.group('minute')}"
            if day_only.group("hour") is not None
            else None
        )
    if normalized_kickoff and normalized_kickoff[0] != actual_date:
        raise ValueError("normalized_kickoff_date_mismatch")
    if raw_time and normalized_kickoff and raw_time != normalized_kickoff[1]:
        raise ValueError("raw_kickoff_time_mismatch")


def _score(text: str, field: str) -> tuple[int, int]:
    match = _SCORE_RE.fullmatch(_plain_text([text]))
    if not match:
        raise ValueError(f"raw_{field}_unparseable")
    return int(match.group(1)), int(match.group(2))


def _canonical_json(value: Any) -> bytes:
    def serialize_date(item: Any) -> str:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f"unsupported canonical JSON value: {type(item).__name__}")

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=serialize_date,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _id_text(value: Any, field: str) -> str:
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9]\d{0,15}", value):
        raise ValueError(f"{field}_invalid")
    return value


def parse_titan_result_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a completed Titan source row against its raw HTML payload."""
    if not isinstance(row, Mapping):
        raise ValueError("source_row_invalid")
    try:
        match_id = _id_text(row.get("match_id"), "source_match_id")
    except ValueError as exc:
        raise ValueError("source_match_id_invalid") from exc
    if not isinstance(row.get("raw"), str) or not row["raw"].strip():
        raise ValueError("missing_raw_record")
    if row.get("status_text") != "完场" or row.get("status_code") != -1:
        raise ValueError("source_not_completed")
    if row.get("source") not in {"history", "live"}:
        raise ValueError("source_namespace_unsupported")

    parser = _TitanRowParser()
    try:
        parser.feed(row["raw"])
        parser.close()
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if parser._row is not None or len(parser.rows) != 1:
        raise ValueError("raw_row_count_mismatch")
    cells = parser.rows[0]
    if len(cells) < 7:
        raise ValueError("raw_cell_count_mismatch")
    raw_ids = set(parser._onclick_ids + parser._sid_ids)
    if not raw_ids:
        raise ValueError("raw_match_id_missing")
    if len(raw_ids) != 1:
        raise ValueError("raw_match_id_conflict")
    if next(iter(raw_ids)) != match_id:
        raise ValueError("raw_match_id_mismatch")

    raw_date_text = _plain_text(cells[1]["text"])
    actual_date = _date_value(row.get("match_date"))
    normalized_kickoff = _kickoff_parts(row.get("kickoff"))
    _check_raw_date(raw_date_text, actual_date, normalized_kickoff)

    raw_status = _plain_text(cells[2]["text"])
    if raw_status not in {"完", "完场"}:
        raise ValueError("raw_status_mismatch")
    raw_home = _plain_text(cells[3]["text"])
    raw_away = _plain_text(cells[5]["text"])
    if not raw_home or _comparison_name(row.get("home_name")) != _comparison_name(raw_home):
        raise ValueError("raw_home_name_mismatch")
    if not raw_away or _comparison_name(row.get("away_name")) != _comparison_name(raw_away):
        raise ValueError("raw_away_name_mismatch")
    raw_full = _score(_plain_text(cells[4]["text"]), "full_score")
    raw_half = _score(_plain_text(cells[6]["text"]), "half_score")
    full = (row.get("home_score"), row.get("away_score"))
    half = (row.get("home_half"), row.get("away_half"))
    if any(type(value) is not int or value < 0 for value in full):
        raise ValueError("normalized_full_score_missing")
    if any(type(value) is not int or value < 0 for value in half):
        raise ValueError("normalized_half_score_missing")
    if raw_full != full:
        raise ValueError("raw_full_score_mismatch")
    if raw_half != half:
        raise ValueError("raw_half_score_mismatch")

    payload = {
        "source_name": SOURCE_NAME,
        "source_table": "matches",
        "source": row["source"],
        "match_id": int(match_id),
        "match_date": actual_date.isoformat(),
        "kickoff": row.get("kickoff"),
        "status_code": row["status_code"],
        "status_text": row["status_text"],
        "home_name": row["home_name"],
        "away_name": row["away_name"],
        "home_score": full[0],
        "away_score": full[1],
        "home_half": half[0],
        "away_half": half[1],
        "raw": row["raw"],
    }
    return {
        "source_match_id": match_id,
        "actual_match_date": actual_date,
        "raw_home_name": raw_home,
        "raw_away_name": raw_away,
        "raw_status": raw_status,
        "team_name_normalization": TEAM_NAME_NORMALIZATION,
        "full_score": full,
        "half_score": half,
        "source_payload": payload,
        "source_payload_sha256": _sha256(payload),
    }


def _comparison_name(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    text = re.sub(r"\s*[(（]中[)）]\s*$", "", text)
    normalized = "".join(text.split())
    return _TEAM_NAME_ALIASES.get(normalized, normalized)


def _as_int(value: Any, reason: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(reason)
    return value


def _as_local_date(value: Any, reason: str) -> date:
    if isinstance(value, datetime):
        return value.astimezone(ZoneInfo("Asia/Shanghai")).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(reason) from exc
        if parsed.tzinfo is None:
            raise ValueError(reason)
        return parsed.astimezone(ZoneInfo("Asia/Shanghai")).date()
    raise ValueError(reason)


def _lottery_link_matches(
    link_evidence: Mapping[str, Any], official_result: Mapping[str, Any]
) -> bool:
    lottery_links = link_evidence.get("lottery_links")
    sporttery_match_id = str(official_result.get("sporttery_match_id") or "")
    if not isinstance(lottery_links, list) or not sporttery_match_id:
        return False
    for item in lottery_links:
        if not isinstance(item, dict):
            continue
        if str(item.get("lottery_match_id")) != sporttery_match_id:
            continue
        official_home_names = {
            _comparison_name(item.get("home_team")),
            _comparison_name(item.get("home_full_name")),
        }
        official_away_names = {
            _comparison_name(item.get("away_team")),
            _comparison_name(item.get("away_full_name")),
        }
        if (
            _comparison_name(official_result.get("official_home_team_name"))
            and _comparison_name(official_result.get("official_away_team_name"))
            and _comparison_name(official_result.get("official_home_team_name"))
            in official_home_names
            and _comparison_name(official_result.get("official_away_team_name"))
            in official_away_names
        ):
            return True
    return False


def _official_result_digest(official_result: Mapping[str, Any]) -> str:
    keys = (
        "official_match_id",
        "sporttery_match_id",
        "business_date",
        "official_home_team_name",
        "official_away_team_name",
        "official_result_status",
        "half_home_goals",
        "half_away_goals",
        "full_home_goals",
        "full_away_goals",
        "official_result_updated_at",
        "official_result_raw_json_sha256",
    )
    normalized = {}
    for key in keys:
        value = official_result.get(key)
        if key == "official_result_raw_json_sha256":
            raw = official_result.get("official_result_raw")
            value = _sha256(raw) if isinstance(raw, Mapping) else None
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        normalized[key] = value
    return _sha256(normalized)


def _official_score_semantics(official_result: Mapping[str, Any]) -> dict[str, Any]:
    raw = official_result.get("official_result_raw")
    if not isinstance(raw, Mapping):
        raise ValueError("official_result_semantics_missing")
    if raw.get("source_name") not in (None, "sporttery"):
        raise ValueError("official_result_source_untrusted")
    result = raw.get("match_result")
    result = result if isinstance(result, Mapping) else raw

    if str(result.get("matchId") or "") != str(official_result.get("sporttery_match_id") or ""):
        raise ValueError("official_result_source_identity_mismatch")
    status = str(result.get("matchResultStatus") or "")
    pool_status = str(result.get("poolStatus") or "")
    if is_void_official_result(raw, result.get("resultStatus")):
        raise ValueError("official_result_is_void")
    if status != "2" and pool_status != "Payout":
        raise ValueError("official_result_semantics_unconfirmed")

    raw_full = _score(str(result.get("sectionsNo999") or ""), "official_full_score")
    raw_half = _score(str(result.get("sectionsNo1") or ""), "official_half_score")
    if raw_full != (
        official_result.get("full_home_goals"),
        official_result.get("full_away_goals"),
    ):
        raise ValueError("official_raw_full_score_mismatch")
    if raw_half != (
        official_result.get("half_home_goals"),
        official_result.get("half_away_goals"),
    ):
        raise ValueError("official_raw_half_score_mismatch")

    artifact = None
    artifact_fields: tuple[str, str] | None = None
    for key, url_key, hash_key in (
        ("source_artifact", "url", "payload_sha256"),
        ("_original_official_result_evidence", "source_url", "source_body_sha256"),
        ("_source_artifact", "source_url", "hash"),
    ):
        candidate = raw.get(key)
        if isinstance(candidate, Mapping) and candidate.get(url_key):
            artifact = candidate
            artifact_fields = (url_key, hash_key)
            break
    if artifact is None or artifact_fields is None:
        raise ValueError("official_result_artifact_missing")
    artifact_url = str(artifact.get(artifact_fields[0]))
    parsed_url = urlsplit(artifact_url)
    if parsed_url.scheme != "https" or parsed_url.hostname not in _OFFICIAL_HOSTS:
        raise ValueError("official_result_artifact_untrusted")
    artifact_sha256 = artifact.get(artifact_fields[1])
    if artifact_sha256 is not None and (
        not isinstance(artifact_sha256, str) or not _DIGEST_RE.fullmatch(artifact_sha256)
    ):
        raise ValueError("official_result_artifact_digest_invalid")

    return {
        "match_result_status": status or None,
        "pool_status": pool_status or None,
        "source_artifact_url": artifact_url,
        "source_artifact_sha256": artifact_sha256,
        "stored_raw_json_sha256": _sha256(raw),
        "score_period": "regulation",
        "score_basis": "on_field",
        "rule_reference": OFFICIAL_RULE_URL,
    }


def build_titan_result_fact(
    parsed: Mapping[str, Any],
    *,
    fixture_id: int,
    official_result: Mapping[str, Any],
    link_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a model-eligible fact only after full source and official checks."""
    if type(fixture_id) is not int or fixture_id <= 0:
        raise ValueError("fixture_id_invalid")
    if not isinstance(official_result, Mapping) or not isinstance(link_evidence, Mapping):
        raise ValueError("verified_identity_evidence_missing")
    source_match_id = _id_text(parsed.get("source_match_id"), "source_match_id")
    official_match_id = _as_int(
        link_evidence.get("official_match_id"), "official_match_identity_mismatch"
    )
    if official_result.get("official_match_id") != official_match_id:
        raise ValueError("official_match_identity_mismatch")

    raw_history_batch_id = link_evidence.get("history_batch_id")
    batch_digest = link_evidence.get("history_content_sha256")
    if raw_history_batch_id is None or batch_digest is None:
        raise ValueError("history_batch_evidence_missing")
    history_batch_id = _as_int(raw_history_batch_id, "history_batch_evidence_invalid")
    if not isinstance(batch_digest, str) or not _DIGEST_RE.fullmatch(batch_digest):
        raise ValueError("history_batch_evidence_invalid")
    if (
        official_result.get("history_batch_id") != history_batch_id
        or official_result.get("history_batch_source") != SOURCE_NAME
        or official_result.get("history_batch_state") != "published"
        or official_result.get("history_content_sha256") != batch_digest
    ):
        raise ValueError("history_batch_evidence_mismatch")
    if (
        str(official_result.get("history_source_match_id")) != source_match_id
        or str(link_evidence.get("history_source_match_id")) != source_match_id
    ):
        raise ValueError("history_source_identity_mismatch")
    if official_result.get("history_match_status") != "finished":
        raise ValueError("history_source_not_finished")
    if official_result.get("official_result_status") != "confirmed":
        raise ValueError("official_result_not_confirmed")
    if official_result.get("official_match_status") != "Settled":
        raise ValueError("official_match_not_settled")
    if official_result.get("sporttery_fixture_id") != fixture_id:
        raise ValueError("official_match_fixture_mismatch")
    if not _lottery_link_matches(link_evidence, official_result):
        raise ValueError("sporttery_source_identity_mismatch")

    home = _comparison_name(parsed.get("raw_home_name"))
    away = _comparison_name(parsed.get("raw_away_name"))
    if (
        not home
        or home != _comparison_name(link_evidence.get("home_team_name"))
        or home != _comparison_name(official_result.get("history_home_team_name"))
        or home != _comparison_name(official_result.get("official_home_team_name"))
    ):
        raise ValueError("linked_home_team_mismatch")
    if (
        not away
        or away != _comparison_name(link_evidence.get("away_team_name"))
        or away != _comparison_name(official_result.get("history_away_team_name"))
        or away != _comparison_name(official_result.get("official_away_team_name"))
    ):
        raise ValueError("linked_away_team_mismatch")

    actual_date = parsed.get("actual_match_date")
    if not isinstance(actual_date, date) or isinstance(actual_date, datetime):
        raise ValueError("actual_match_date_invalid")
    history_date = _as_local_date(
        official_result.get("history_kickoff_at"), "history_kickoff_date_missing"
    )
    if history_date != actual_date:
        raise ValueError("history_kickoff_date_mismatch")
    if (
        official_result.get("history_home_goals") != parsed.get("full_score", (None, None))[0]
        or official_result.get("history_away_goals") != parsed.get("full_score", (None, None))[1]
    ):
        raise ValueError("history_full_score_mismatch")
    if (
        official_result.get("full_home_goals") != parsed.get("full_score", (None, None))[0]
        or official_result.get("full_away_goals") != parsed.get("full_score", (None, None))[1]
    ):
        raise ValueError("official_full_score_mismatch")
    if (
        official_result.get("half_home_goals") != parsed.get("half_score", (None, None))[0]
        or official_result.get("half_away_goals") != parsed.get("half_score", (None, None))[1]
    ):
        raise ValueError("official_half_score_mismatch")
    if (
        official_result.get("half_home_goals") is None
        or official_result.get("half_away_goals") is None
    ):
        raise ValueError("official_half_score_missing")
    if (
        official_result.get("full_home_goals") is None
        or official_result.get("full_away_goals") is None
    ):
        raise ValueError("official_full_score_missing")
    semantics = _official_score_semantics(official_result)

    payload = parsed["source_payload"]
    evidence = {
        "contract": EVIDENCE_CONTRACT,
        "identity": {
            "fixture_id": fixture_id,
            "source_name": SOURCE_NAME,
            "id_system": ID_SYSTEM,
            "source_match_id": source_match_id,
        },
        "source_reference": {
            "table": "matches",
            "record_id": source_match_id,
            "row_sha256": parsed["source_payload_sha256"],
            "raw_normalized_fields_match": True,
            "team_name_normalization": parsed["team_name_normalization"],
        },
        "history_reference": {
            "batch_id": history_batch_id,
            "content_sha256": batch_digest,
            "normalization_version": official_result.get("history_normalization_version"),
        },
        "official_result_reference": {
            "source_name": "sporttery",
            "official_match_id": official_match_id,
            "source_match_id": str(official_result["sporttery_match_id"]),
            "result_status": "confirmed",
            "official_match_status": "Settled",
            "facts_sha256": _official_result_digest(official_result),
            **semantics,
            "score_semantics": (
                "Sporttery football result: referee-determined score at the end of "
                "90 minutes including added time"
            ),
        },
    }
    return {
        "fixture_id": fixture_id,
        "source_name": SOURCE_NAME,
        "id_system": ID_SYSTEM,
        "source_match_id": source_match_id,
        "actual_match_date": actual_date,
        "actual_kickoff_at": None,
        "kickoff_time_precision": "date_only",
        "match_status": "completed",
        "score_basis": semantics["score_basis"],
        "score_period": semantics["score_period"],
        "half_home_goals": parsed["half_score"][0],
        "half_away_goals": parsed["half_score"][1],
        "full_home_goals": parsed["full_score"][0],
        "full_away_goals": parsed["full_score"][1],
        "source_published_at": None,
        "source_payload": payload,
        "evidence": evidence,
    }


_DB_CONTEXT_SQL = """
WITH links AS (
    SELECT l.source_match_id,l.fixture_id,l.evidence,
           CASE WHEN l.evidence->>'history_batch_id' ~ '^[1-9][0-9]{0,17}$'
                THEN (l.evidence->>'history_batch_id')::bigint END AS history_batch_id,
           CASE WHEN l.evidence->>'official_match_id' ~ '^[1-9][0-9]{0,17}$'
                THEN (l.evidence->>'official_match_id')::bigint END AS expected_official_match_id
    FROM football_fixture_source_links l
    WHERE l.source_name='titan007' AND l.id_system='matchId'
      AND l.source_match_id=ANY(%s)
)
SELECT l.source_match_id,l.fixture_id,l.evidence,
       b.id AS history_batch_id,b.source_name AS history_batch_source,
       b.state AS history_batch_state,b.content_sha256 AS history_content_sha256,
       b.normalization_version AS history_normalization_version,
       h.source_match_id AS history_source_match_id,
       h.match_status AS history_match_status,h.kickoff_at AS history_kickoff_at,
       h.home_name AS history_home_team_name,h.away_name AS history_away_team_name,
       h.home_goals AS history_home_goals,h.away_goals AS history_away_goals,
       om.id AS official_match_id,om.source_match_id AS sporttery_match_id,
       om.match_status AS official_match_status,
       om.home_team_name AS official_home_team_name,
       om.away_team_name AS official_away_team_name,om.business_date,
       r.result_status AS official_result_status,
       r.half_home_goals,r.half_away_goals,r.full_home_goals,r.full_away_goals,
       r.updated_at AS official_result_updated_at,r.raw_json AS official_result_raw,
       sl.fixture_id AS sporttery_fixture_id
FROM links l
LEFT JOIN football_history_batches b ON b.id=l.history_batch_id
LEFT JOIN football_history_matches h ON h.batch_id=b.id
    AND h.source_match_id=l.source_match_id::bigint
LEFT JOIN official_matches om ON om.id=l.expected_official_match_id
LEFT JOIN official_results r ON r.match_id=om.id
LEFT JOIN football_fixture_source_links sl ON sl.fixture_id=l.fixture_id
    AND sl.source_name='sporttery' AND sl.id_system='jc.matchId'
    AND sl.source_match_id=om.source_match_id
ORDER BY l.source_match_id
"""


def _database_context(conn: Any, source_match_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not source_match_ids:
        return {}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(_DB_CONTEXT_SQL, (source_match_ids,))
        return {str(row["source_match_id"]): dict(row) for row in cur.fetchall()}


def import_titan_result_rows(
    conn: Any,
    rows: Iterable[Mapping[str, Any]],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or append a batch; caller owns the transaction and rollback."""
    from psycopg2.extensions import TRANSACTION_STATUS_IDLE

    if conn.autocommit:
        raise RuntimeError("result import refuses autocommit connections")
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise RuntimeError("result import requires a fresh transaction; commit or rollback first")
    raw_rows = [dict(row) for row in rows]
    if apply:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cur.execute("SET LOCAL lock_timeout='2s'")
            cur.execute("SET LOCAL statement_timeout='30s'")
    else:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout='30s'")

    parsed_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    decisions: list[dict[str, Any]] = []
    seen: Counter[str] = Counter()
    for row in raw_rows:
        raw_id = row.get("match_id", row.get("source_match_id"))
        source_id = str(raw_id) if raw_id is not None else None
        try:
            parsed = parse_titan_result_row(row)
        except ValueError as exc:
            decisions.append(
                {"source_match_id": source_id, "status": "rejected", "reason": str(exc)}
            )
            continue
        seen[parsed["source_match_id"]] += 1
        parsed_rows.append((parsed, row))

    duplicated = {source_id for source_id, count in seen.items() if count > 1}
    query_ids = sorted(seen.keys() - duplicated)
    contexts = _database_context(conn, query_ids)
    accepted: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for parsed, row in parsed_rows:
        source_id = parsed["source_match_id"]
        if source_id in duplicated:
            decisions.append(
                {
                    "source_match_id": source_id,
                    "status": "rejected",
                    "reason": "duplicate_source_record_in_package",
                }
            )
            continue
        context = contexts.get(source_id)
        if context is None:
            decisions.append(
                {
                    "source_match_id": source_id,
                    "status": "rejected",
                    "reason": "titan_source_link_missing",
                }
            )
            continue
        try:
            fact = build_titan_result_fact(
                parsed,
                fixture_id=context["fixture_id"],
                official_result=context,
                link_evidence=context["evidence"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            reason = (
                str(exc) if isinstance(exc, ValueError) else "verified_identity_evidence_invalid"
            )
            decisions.append({"source_match_id": source_id, "status": "rejected", "reason": reason})
            continue
        accepted.append((fact, row))
        decisions.append({"source_match_id": source_id, "status": "eligible", "reason": None})

    if apply:
        eligible_ids = sorted(fact["source_match_id"] for fact, _ in accepted)
        locked_contexts = _database_context_for_apply(conn, eligible_ids)
        if set(locked_contexts) != set(eligible_ids):
            raise RuntimeError(
                "verified source identity changed during import; transaction rolled back"
            )
        eligible_id_set = set(eligible_ids)
        source_rows = {
            parsed["source_match_id"]: row
            for parsed, row in parsed_rows
            if parsed["source_match_id"] in eligible_id_set
        }
        decisions_by_id = {
            item["source_match_id"]: item for item in decisions if item["status"] == "eligible"
        }
        for fact, _ in accepted:
            source_id = fact["source_match_id"]
            locked = locked_contexts[source_id]
            parsed = parse_titan_result_row(source_rows[source_id])
            rechecked = build_titan_result_fact(
                parsed,
                fixture_id=locked["fixture_id"],
                official_result=locked,
                link_evidence=locked["evidence"],
            )
            if _canonical_json(rechecked) != _canonical_json(fact):
                raise RuntimeError(
                    "verified source facts changed during import; transaction rolled back"
                )
            stored = store_result_fact(conn, fact)
            decision = decisions_by_id[source_id]
            decision.update(
                status="inserted" if stored["inserted"] else "already_present",
                fact_id=stored["id"],
                model_eligible=stored["model_eligible"],
            )

    counts = Counter(item["status"] for item in decisions)
    reasons = Counter(item["reason"] for item in decisions if item.get("reason"))
    return {
        "input_rows": len(raw_rows),
        "counts": dict(sorted(counts.items())),
        "rejection_reasons": dict(sorted(reasons.items())),
        "decisions": sorted(
            decisions, key=lambda item: (item.get("source_match_id") or "", item["status"])
        ),
    }


def _database_context_for_apply(
    conn: Any, source_match_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Re-read all evidence rows in the same serializable transaction."""
    if not source_match_ids:
        return {}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(_DB_CONTEXT_SQL, (source_match_ids,))
        return {str(row["source_match_id"]): dict(row) for row in cur.fetchall()}


def read_titan_result_rows(
    source_db: str | Path, source_match_ids: Iterable[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read requested rows from SQLite without creating or modifying the cache."""
    ids = sorted({_id_text(value, "source_match_id") for value in source_match_ids})
    if not ids:
        return [], []
    path = Path(source_db).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        result: list[dict[str, Any]] = []
        for offset in range(0, len(ids), 400):
            chunk = ids[offset : offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            cur = conn.execute(
                f"""SELECT match_id,source,match_date,kickoff,status_code,status_text,
                           home_name,away_name,home_score,away_score,home_half,away_half,raw
                    FROM matches WHERE match_id IN ({placeholders}) ORDER BY match_id""",
                [int(value) for value in chunk],
            )
            result.extend(dict(row) for row in cur.fetchall())
    finally:
        conn.close()
    found = {str(row["match_id"]) for row in result}
    return result, [source_id for source_id in ids if source_id not in found]


def _load_package(path: str) -> TitanResultPackage:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        candidate = json.load(handle)
    if not isinstance(candidate, dict):
        raise ValueError("source_package_contract_invalid")
    package = cast(dict[str, Any], candidate)
    records = package.get("records")
    missing_source_ids = package.get("missing_source_ids")
    requested_count = package.get("requested_count")
    record_count = package.get("record_count")
    requested_ids_sha256 = package.get("requested_ids_sha256")
    source_database = package.get("source_database")
    if (
        package.get("contract") != PACKAGE_CONTRACT
        or not isinstance(records, list)
        or not isinstance(missing_source_ids, list)
        or type(requested_count) is not int
        or type(record_count) is not int
        or not isinstance(requested_ids_sha256, str)
        or not _DIGEST_RE.fullmatch(requested_ids_sha256)
        or not isinstance(source_database, str)
        or package.get("source_table") != "matches"
        or record_count != len(records)
        or record_count + len(missing_source_ids) != requested_count
    ):
        raise ValueError("source_package_contract_invalid")
    record_ids: list[str] = []
    normalized_records: list[Mapping[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("source_package_contract_invalid")
        record = cast(Mapping[str, Any], row)
        normalized_records.append(record)
        record_ids.append(_id_text(record.get("match_id"), "source_match_id"))
    missing_ids = [_id_text(source_id, "source_match_id") for source_id in missing_source_ids]
    requested_ids = record_ids + missing_ids
    if (
        len(set(requested_ids)) != requested_count
        or _sha256(sorted(requested_ids)) != requested_ids_sha256
    ):
        raise ValueError("source_package_manifest_mismatch")
    return {
        "contract": PACKAGE_CONTRACT,
        "source_database": source_database,
        "source_table": "matches",
        "requested_ids_sha256": requested_ids_sha256,
        "requested_count": requested_count,
        "record_count": record_count,
        "missing_source_ids": missing_ids,
        "records": normalized_records,
    }


def _export_destination(source_db: str | Path, output: str | Path) -> Path:
    source = Path(source_db).expanduser().resolve(strict=True)
    destination = Path(output).expanduser()
    if destination.resolve(strict=False) == source:
        raise ValueError("export_output_must_not_overwrite_source")
    return destination.absolute()


def _atomic_write_package(path: Path, output: str, *, compressed: bool) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    try:
        if compressed:
            with gzip.open(temporary_name, "wt", encoding="utf-8", compresslevel=6) as handle:
                handle.write(output)
        else:
            with open(temporary_name, "w", encoding="utf-8") as handle:
                handle.write(output + "\n")
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _write_json(path: str, value: Any) -> None:
    output = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
    if path == "-":
        sys.stdout.write(output)
        return
    Path(path).expanduser().write_text(output, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="export only explicitly named Titan match rows")
    export.add_argument("--source-db", required=True)
    export.add_argument(
        "--match-ids", required=True, help="UTF-8 text file, one positive MatchId per line"
    )
    export.add_argument("--output", required=True)
    importer = commands.add_parser("import", help="preview or append a verified package")
    importer.add_argument("--input", required=True)
    importer.add_argument("--report", default="-")
    importer.add_argument("--apply-production", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "export":
        ids = [
            line.strip()
            for line in Path(args.match_ids).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        destination = _export_destination(args.source_db, args.output)
        records, missing = read_titan_result_rows(args.source_db, ids)
        export_package = {
            "contract": PACKAGE_CONTRACT,
            "source_database": Path(args.source_db).name,
            "source_table": "matches",
            "requested_ids_sha256": _sha256(
                sorted({_id_text(value, "source_match_id") for value in ids})
            ),
            "requested_count": len(set(ids)),
            "record_count": len(records),
            "missing_source_ids": missing,
            "records": records,
        }
        output = json.dumps(
            export_package, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        _atomic_write_package(
            destination,
            output,
            compressed=args.output.endswith(".gz"),
        )
        print(
            json.dumps(
                {
                    "requested": len(set(ids)),
                    "exported": len(records),
                    "missing": len(missing),
                    "output": args.output,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.apply_production and os.environ.get("FQP_RESULT_FACT_IMPORT_TARGET") != "production":
        raise SystemExit(
            "BLOCKED: set FQP_RESULT_FACT_IMPORT_TARGET=production for an explicit production write"
        )
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("BLOCKED: DATABASE_URL is required; credentials are never printed")
    import_package = _load_package(args.input)
    with closing(psycopg2.connect(dsn, connect_timeout=5)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT current_user,current_database(),r.rolsuper
                   FROM pg_roles r WHERE r.rolname=current_user"""
            )
            user, database, is_superuser = cur.fetchone()
        if user != "fqp" or database != "fqp" or is_superuser:
            raise SystemExit(
                "BLOCKED: result import requires the non-superuser fqp role in the fqp database"
            )
        conn.commit()
        with conn:
            report = import_titan_result_rows(
                conn, import_package["records"], apply=args.apply_production
            )
    report.update(
        contract=PACKAGE_CONTRACT,
        source_database=import_package["source_database"],
        requested_count=import_package["requested_count"],
        missing_source_ids=import_package["missing_source_ids"],
        applied=bool(args.apply_production),
    )
    _write_json(args.report, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
