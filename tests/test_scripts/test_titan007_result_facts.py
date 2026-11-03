"""Fixed raw-source contract tests for the Titan result-fact importer."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime

import pytest

from scripts.titan007_result_facts import (
    PACKAGE_CONTRACT,
    _atomic_write_package,
    _export_destination,
    _load_package,
    build_titan_result_fact,
    main,
    parse_titan_result_row,
    read_titan_result_rows,
)


def _raw_row(
    *,
    match_id: int = 123456,
    raw_match_id: int | None = None,
    date_text: str = "22日20:00",
    status: str = "完",
    home: str = "阿森纳(中)",
    full: tuple[int, int] = (2, 1),
    away: str = "切尔西",
    half: tuple[int, int] = (1, 0),
    raw_home: str | None = None,
    raw_full: tuple[int, int] | None = None,
    raw_away: str | None = None,
    raw_half: tuple[int, int] | None = None,
) -> dict:
    raw_match_id = match_id if raw_match_id is None else raw_match_id
    raw_home = home if raw_home is None else raw_home
    raw_full = full if raw_full is None else raw_full
    raw_away = away if raw_away is None else raw_away
    raw_half = half if raw_half is None else raw_half
    return {
        "match_id": match_id,
        "source": "history",
        "match_date": "2026-11-22",
        "kickoff": "2026-11-22 20:00",
        "status_code": -1,
        "status_text": "完场",
        "home_name": home,
        "away_name": away,
        "home_score": full[0],
        "away_score": full[1],
        "home_half": half[0],
        "away_half": half[1],
        "result_confirmed_at": "2026-11-22T22:00:00",
        "source_published_at": None,
        "raw": (
            '<tr><td>英超</td><td>'
            f"{date_text}"
            f"</td><td class='style1'>{status}</td>"
            f"<td align='right'>{raw_home}</td>"
            f"<td class='style1' onclick='showgoallist({raw_match_id})'>"
            f"<font>{raw_full[0]}</font>-<font>{raw_full[1]}</font></td>"
            f"<td align='left'>{raw_away}</td>"
            f"<td><font>{raw_half[0]}</font>-<font>{raw_half[1]}</font></td></tr>"
        ),
    }


def _official_result(**changes) -> dict:
    result = {
        "result_status": "confirmed",
        "official_match_id": 9876,
        "sporttery_match_id": "1001",
        "official_home_team_name": "阿森纳",
        "official_away_team_name": "切尔西",
        "business_date": date(2026, 11, 22),
        "official_result_status": "confirmed",
        "official_match_status": "Settled",
        "official_result_updated_at": datetime(2026, 11, 22, 22, 0, tzinfo=UTC),
        "half_home_goals": 1,
        "half_away_goals": 0,
        "full_home_goals": 2,
        "full_away_goals": 1,
        "sporttery_fixture_id": 456,
        "history_batch_id": 12,
        "history_batch_source": "titan007",
        "history_batch_state": "published",
        "history_content_sha256": "a" * 64,
        "history_normalization_version": "fixed/v1",
        "history_source_match_id": "123456",
        "history_official_match_id": None,
        "history_match_status": "finished",
        "history_kickoff_at": datetime(2026, 11, 22, 12, 0, tzinfo=UTC),
        "history_home_team_name": "阿森纳",
        "history_away_team_name": "切尔西",
        "history_home_goals": 2,
        "history_away_goals": 1,
        "official_result_raw": {
            "source_name": "sporttery",
            "match_result": {
                "matchId": 1001,
                "matchResultStatus": "2",
                "poolStatus": "Payout",
                "resultStatus": "",
                "sectionsNo1": "1:0",
                "sectionsNo999": "2:1",
            },
            "source_artifact": {
                "url": "https://webapi.sporttery.cn/gateway/uniform/football/getUniformMatchResultV1.qry",
                "captured_at": "2026-11-22T22:00:00+08:00",
                "payload_sha256": "c" * 64,
            },
        },
    }
    result.update(changes)
    return result


def test_parse_titan_result_row_checks_raw_html_against_normalized_columns():
    parsed = parse_titan_result_row(_raw_row())

    assert parsed["source_match_id"] == "123456"
    assert parsed["actual_match_date"] == date(2026, 11, 22)
    assert parsed["raw_home_name"] == "阿森纳(中)"
    assert parsed["raw_away_name"] == "切尔西"
    assert parsed["full_score"] == (2, 1)
    assert parsed["half_score"] == (1, 0)
    assert parsed["raw_status"] == "完"
    assert "result_confirmed_at" not in parsed["source_payload"]


@pytest.mark.parametrize(
    ("canonical", "alias"),
    [
        ("布赖顿", "布莱顿"),
        ("伍尔弗汉普顿", "狼队"),
        ("谢菲尔德联", "谢菲尔德联队"),
        ("莱切斯特城", "莱斯特城"),
    ],
)
def test_parse_titan_result_row_accepts_only_documented_name_aliases(canonical, alias):
    row = _raw_row(away=canonical, raw_away=alias)

    parsed = parse_titan_result_row(row)

    assert parsed["raw_away_name"] == alias
    assert parsed["team_name_normalization"] == "titan007-cn-explicit-aliases/v2"


def test_parse_titan_result_row_ignores_neutral_venue_marker():
    row = _raw_row(home="阿森纳", raw_home="阿森纳(中)")

    parsed = parse_titan_result_row(row)

    assert parsed["raw_home_name"] == "阿森纳(中)"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"raw_match_id": 123457}, "raw_match_id_mismatch"),
        ({"status": "中"}, "raw_status_mismatch"),
        ({"raw_home": "曼城"}, "raw_home_name_mismatch"),
        ({"raw_away": "曼城"}, "raw_away_name_mismatch"),
        ({"raw_full": (3, 1)}, "raw_full_score_mismatch"),
        ({"raw_half": (0, 0)}, "raw_half_score_mismatch"),
        ({"date_text": "21日20:00"}, "raw_match_date_mismatch"),
    ],
)
def test_parse_titan_result_row_rejects_raw_and_normalized_conflicts(changes, reason):
    with pytest.raises(ValueError, match=reason):
        parse_titan_result_row(_raw_row(**changes))


@pytest.mark.parametrize(
    ("status_text", "status_code", "reason"),
    [
        ("推迟", -14, "source_not_completed"),
        ("取消", -10, "source_not_completed"),
        ("腰斩", -12, "source_not_completed"),
        ("完场", 0, "source_not_completed"),
    ],
)
def test_parse_titan_result_row_only_accepts_explicit_completed_state(
    status_text, status_code, reason
):
    row = _raw_row()
    row["status_text"] = status_text
    row["status_code"] = status_code
    with pytest.raises(ValueError, match=reason):
        parse_titan_result_row(row)


def test_parse_titan_result_row_requires_full_raw_date_and_score_fields():
    row = _raw_row()
    row["raw"] = None
    with pytest.raises(ValueError, match="missing_raw_record"):
        parse_titan_result_row(row)

    row = _raw_row()
    row["home_half"] = None
    with pytest.raises(ValueError, match="normalized_half_score_missing"):
        parse_titan_result_row(row)


def test_build_titan_result_fact_requires_official_confirmed_identity_and_scores():
    parsed = parse_titan_result_row(_raw_row())
    fact = build_titan_result_fact(
        parsed,
        fixture_id=456,
        official_result=_official_result(),
        link_evidence={
            "official_match_id": 9876,
            "history_batch_id": 12,
            "history_content_sha256": "a" * 64,
            "history_source_match_id": "123456",
            "home_team_name": "阿森纳",
            "away_team_name": "切尔西",
            "lottery_links": [
                {
                    "lottery_match_id": 1001,
                    "home_team": "阿森纳",
                    "home_full_name": "阿森纳",
                    "away_team": "切尔西",
                    "away_full_name": "切尔西",
                }
            ],
        },
    )

    assert fact["fixture_id"] == 456
    assert fact["source_match_id"] == "123456"
    assert fact["actual_match_date"] == date(2026, 11, 22)
    assert fact["kickoff_time_precision"] == "date_only"
    assert fact["actual_kickoff_at"] is None
    assert fact["match_status"] == "completed"
    assert fact["score_basis"] == "on_field"
    assert fact["score_period"] == "regulation"
    assert fact["source_published_at"] is None
    assert (
        fact["evidence"]["source_reference"]["team_name_normalization"]
        == "titan007-cn-explicit-aliases/v2"
    )
    assert fact["evidence"]["official_result_reference"]["official_match_id"] == 9876
    assert fact["evidence"]["official_result_reference"]["rule_reference"].endswith("gid=9")
    assert fact["evidence"]["official_result_reference"]["source_artifact_sha256"] == "c" * 64


def test_build_titan_result_fact_supports_flat_official_capture_format():
    parsed = parse_titan_result_row(_raw_row())
    official_result = _official_result()
    flat_result = official_result["official_result_raw"]["match_result"].copy()
    flat_result["_original_official_result_evidence"] = {
        "source_url": "https://webapi.sporttery.cn/gateway/uniform/football/getUniformMatchResultV1.qry",
        "source_body_sha256": "d" * 64,
    }
    official_result["official_result_raw"] = flat_result
    link_evidence = {
        "official_match_id": 9876,
        "history_batch_id": 12,
        "history_content_sha256": "a" * 64,
        "history_source_match_id": "123456",
        "home_team_name": "阿森纳",
        "away_team_name": "切尔西",
        "lottery_links": [
            {
                "lottery_match_id": 1001,
                "home_team": "阿森纳",
                "home_full_name": "阿森纳",
                "away_team": "切尔西",
                "away_full_name": "切尔西",
            }
        ],
    }

    fact = build_titan_result_fact(
        parsed,
        fixture_id=456,
        official_result=official_result,
        link_evidence=link_evidence,
    )

    assert fact["score_basis"] == "on_field"
    assert fact["score_period"] == "regulation"
    assert fact["evidence"]["official_result_reference"]["source_artifact_sha256"] == "d" * 64


@pytest.mark.parametrize(
    ("official_changes", "link_changes", "reason"),
    [
        ({"official_result_status": "pending"}, {}, "official_result_not_confirmed"),
        ({"official_match_status": "scheduled"}, {}, "official_match_not_settled"),
        ({"full_home_goals": 3}, {}, "official_full_score_mismatch"),
        ({"half_away_goals": 1}, {}, "official_half_score_mismatch"),
        ({}, {"official_match_id": 9877}, "official_match_identity_mismatch"),
        ({}, {"home_team_name": "曼城"}, "linked_home_team_mismatch"),
        ({}, {"history_content_sha256": "bad"}, "history_batch_evidence_invalid"),
        ({}, {"history_batch_id": None, "history_content_sha256": None}, "history_batch_evidence_missing"),
        ({"official_result_raw": None}, {}, "official_result_semantics_missing"),
        (
            {
                "official_result_raw": {
                    "source_name": "sporttery",
                    "match_result": {
                        "matchId": 1001,
                        "poolStatus": "Refund",
                        "sectionsNo1": "1:0",
                        "sectionsNo999": "2:1",
                    },
                    "source_artifact": {"url": "https://www.sporttery.cn/jc/zqsgkj/"},
                }
            },
            {},
            "official_result_is_void",
        ),
        (
            {
                "official_result_raw": {
                    "source_name": "sporttery",
                    "match_result": {
                        "matchId": 9999,
                        "matchResultStatus": "2",
                        "sectionsNo1": "1:0",
                        "sectionsNo999": "2:1",
                    },
                    "source_artifact": {"url": "https://www.sporttery.cn/jc/zqsgkj/"},
                }
            },
            {},
            "official_result_source_identity_mismatch",
        ),
        (
            {
                "official_result_raw": {
                    "source_name": "sporttery",
                    "match_result": {
                        "matchId": 1001,
                        "matchResultStatus": "2",
                        "sectionsNo1": "1:0",
                        "sectionsNo999": "3:1",
                    },
                    "source_artifact": {"url": "https://www.sporttery.cn/jc/zqsgkj/"},
                }
            },
            {},
            "official_raw_full_score_mismatch",
        ),
        (
            {
                "official_result_raw": {
                    "source_name": "sporttery",
                    "match_result": {
                        "matchId": 1001,
                        "matchResultStatus": "2",
                        "sectionsNo1": "1:0",
                        "sectionsNo999": "2:1",
                    },
                    "source_artifact": {"url": "https://example.invalid/result"},
                }
            },
            {},
            "official_result_artifact_untrusted",
        ),
    ],
)
def test_build_titan_result_fact_rejects_unverified_or_conflicting_evidence(
    official_changes, link_changes, reason
):
    parsed = parse_titan_result_row(_raw_row())
    link_evidence = {
        "official_match_id": 9876,
        "history_batch_id": 12,
        "history_content_sha256": "a" * 64,
        "history_source_match_id": "123456",
        "home_team_name": "阿森纳",
        "away_team_name": "切尔西",
        "lottery_links": [
            {
                "lottery_match_id": 1001,
                "home_team": "阿森纳",
                "home_full_name": "阿森纳",
                "away_team": "切尔西",
                "away_full_name": "切尔西",
            }
        ],
    }
    link_evidence.update(link_changes)
    with pytest.raises(ValueError, match=reason):
        build_titan_result_fact(
            parsed,
            fixture_id=456,
            official_result=_official_result(**official_changes),
            link_evidence=link_evidence,
        )


def test_export_refuses_source_path_and_symlink_alias(tmp_path):
    source = tmp_path / "source.sqlite"
    source.write_bytes(b"sqlite-source-marker")
    alias = tmp_path / "source-alias.sqlite"
    alias.symlink_to(source)

    with pytest.raises(ValueError, match="export_output_must_not_overwrite_source"):
        _export_destination(source, source)
    with pytest.raises(ValueError, match="export_output_must_not_overwrite_source"):
        _export_destination(source, alias)
    assert source.read_bytes() == b"sqlite-source-marker"


@pytest.mark.parametrize("compressed", [False, True])
def test_export_writes_package_atomically(tmp_path, compressed):
    output_path = tmp_path / ("package.json.gz" if compressed else "package.json")
    requested_ids_sha256 = hashlib.sha256(b"[]").hexdigest()
    payload = json.dumps(
        {
            "contract": PACKAGE_CONTRACT,
            "source_database": "empty.sqlite",
            "source_table": "matches",
            "requested_ids_sha256": requested_ids_sha256,
            "requested_count": 0,
            "record_count": 0,
            "missing_source_ids": [],
            "records": [],
        },
        separators=(",", ":"),
    )

    _atomic_write_package(output_path, payload, compressed=compressed)

    assert _load_package(str(output_path)) == {
        "contract": PACKAGE_CONTRACT,
        "source_database": "empty.sqlite",
        "source_table": "matches",
        "requested_ids_sha256": requested_ids_sha256,
        "requested_count": 0,
        "record_count": 0,
        "missing_source_ids": [],
        "records": [],
    }


def test_apply_cli_requires_explicit_production_target_before_opening_package(monkeypatch):
    monkeypatch.delenv("FQP_RESULT_FACT_IMPORT_TARGET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit, match="explicit production write"):
        main(["import", "--input", "does-not-exist.json.gz", "--apply-production"])


@pytest.mark.parametrize(
    ("user", "database", "is_superuser"),
    [("admin", "fqp", False), ("fqp", "other", False), ("fqp", "fqp", True)],
)
def test_apply_cli_rejects_wrong_runtime_role(
    monkeypatch, tmp_path, user, database, is_superuser
):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *_args):
            return None

        def fetchone(self):
            return user, database, is_superuser

    class Connection:
        closed = False

        def cursor(self):
            return Cursor()

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr("scripts.titan007_result_facts.psycopg2.connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test.invalid/fqp")
    monkeypatch.setenv("FQP_RESULT_FACT_IMPORT_TARGET", "production")
    package = tmp_path / "empty.json"
    package.write_text(
        json.dumps(
            {
                "contract": PACKAGE_CONTRACT,
                "source_database": "empty.sqlite",
                "source_table": "matches",
                "requested_ids_sha256": hashlib.sha256(b"[]").hexdigest(),
                "requested_count": 0,
                "record_count": 0,
                "missing_source_ids": [],
                "records": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="non-superuser fqp role"):
        main(["import", "--input", str(package), "--apply-production"])

    assert connection.closed is True


def test_package_loader_rejects_contract_or_record_count_mismatch(tmp_path):
    package = tmp_path / "invalid.json"
    package.write_text(
        json.dumps({"contract": "wrong", "record_count": 1, "records": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source_package_contract_invalid"):
        _load_package(str(package))


def test_sqlite_source_export_is_read_only(tmp_path):
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as conn:
        conn.execute(
            """CREATE TABLE matches (
                match_id INTEGER PRIMARY KEY,source TEXT,match_date TEXT,kickoff TEXT,
                status_code INTEGER,status_text TEXT,home_name TEXT,away_name TEXT,
                home_score INTEGER,away_score INTEGER,home_half INTEGER,away_half INTEGER,raw TEXT
            )"""
        )
        conn.execute(
            """INSERT INTO matches VALUES
               (1,'history','2026-11-22','2026-11-22 20:00',-1,'完场','主队','客队',1,0,0,0,'<tr/>')"""
        )
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    rows, missing = read_titan_result_rows(source, ["1"])

    assert len(rows) == 1
    assert missing == []
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
