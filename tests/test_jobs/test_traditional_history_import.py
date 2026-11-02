import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from scripts.traditional_history_import import (
    _local_database_parameters,
    _pool_raw_hash,
    _prepare_fill_header,
    _prepare_fill_member,
    apply_issue_batch,
    load_issue_batch,
)


@pytest.mark.parametrize(
    "script_name",
    ("traditional_history_import.py", "traditional_history_type_repair.py"),
)
def test_standalone_cli_help_works_from_repository_root(script_name: str) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / script_name

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def _write_inputs(
    root: Path,
    *,
    readiness: str = "candidate_new_issue",
    production_state: str = "missing_issue_key",
    exact_slots: bool | None = None,
) -> tuple[Path, Path, Path]:
    preview = root / "preview.csv"
    manifest = root / "manifest.csv"
    summary = root / "manifest.json"
    rows = []
    for match_order in range(1, 7):
        unplayed = match_order == 1
        rows.append(
            {
                "game_type": "bqc6",
                "issue_no": "21062",
                "source_game_no": "98",
                "source_game_no_source": "sporttery_history_api",
                "production_member_slot_exact_team_date": str(
                    production_state == "existing_issue_matches_source_api"
                    if exact_slots is None
                    else exact_slots
                ).lower(),
                "match_order": str(match_order),
                "expected_slot_count": "6",
                "history_game_name": "6场半全场",
                "history_competition": "国际赛",
                "history_home": f"主队{match_order}",
                "history_away": f"客队{match_order}",
                "kickoff_date": "2021-06-05",
                "kickoff_time": "",
                "kickoff_time_precision": "date_only",
                "history_sale_start": "2021-06-02 20:00:00",
                "history_sale_stop": "2021-06-04 22:00:00",
                "history_draw_time": "2021-06-06",
                "kickoff_evidence_json": json.dumps(
                    {"selected_date_source": "sporttery_history_api"}
                ),
                "notice_competition": "国际赛",
                "notice_home": "待定" if match_order == 2 else f"主队{match_order}",
                "notice_away": "待定" if match_order == 2 else f"客队{match_order}",
                "notice_match_date": "2021-06-05",
                "notice_id": "82339",
                "notice_url": "https://example.invalid/notice/82339",
                "notice_has_later_incomplete": "false",
                "notice_api_reconciliation": (
                    "placeholder_resolved_same_date"
                    if match_order == 2
                    else "exact_name_date_match"
                ),
                "full_score_source_text": "*" if unplayed else "0:1",
                "half_score_source_text": "",
                "source_full_home_goals": "" if unplayed else "0",
                "source_full_away_goals": "" if unplayed else "1",
                "source_half_home_goals": "",
                "source_half_away_goals": "",
                "source_product_result_code": "*,*" if unplayed else "1,0",
                "source_result_semantics_key": "sporttery_game_no_98",
                "source_result_source": "sporttery_history_api",
                "source_result_evidence_json": json.dumps(
                    {"game_no": 98, "match_num": match_order}
                ),
                "score_source_state": (
                    "source_marks_unplayed_or_unparsed" if unplayed else "present"
                ),
                "sporttery_match_id": str(900000 + match_order),
                "titan_match_id_direct": "",
                "titan_match_id_candidate": "",
                "identity_candidate_state": "official_sporttery_source_id_available_not_linked",
                "history_mirror_updated_at": "2026-10-31T16:53:33",
            }
        )
    with preview.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest_rows = [
        {
            "game_type": "bqc6",
            "issue_no": "21062",
            "source_game_no": "98",
            "source_game_no_source": "sporttery_history_api",
            "expected_slots": "6",
            "preview_rows": "6",
            "production_issue_state": production_state,
            "readiness": readiness,
            "blocking_reasons": "",
            "evidence_flags": "notice_api_slot_disagreement_or_placeholder;official_source_marks_unplayed_or_refund",
            "production_member_slot_exact_team_date": str(
                production_state == "existing_issue_matches_source_api"
                if exact_slots is None
                else exact_slots
            ).lower(),
        }
    ]
    with manifest.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)
    summary.write_text(
        json.dumps(
            {
                "input": preview.name,
                "input_sha256": hashlib.sha256(preview.read_bytes()).hexdigest(),
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "issue_keys": 1,
                "can_run_as_data_load": False,
            }
        ),
        encoding="utf-8",
    )
    return preview, manifest, summary


def test_import_plan_keeps_api_slots_and_notice_and_unplayed_evidence(tmp_path: Path) -> None:
    preview, manifest, summary = _write_inputs(tmp_path)

    batch = load_issue_batch(preview, manifest, summary, offset=0, limit=10)

    assert batch["selected_issue_count"] == 1
    assert batch["selected_member_count"] == 6
    assert batch["manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    issue = batch["issues"][0]
    assert issue["game_type"] == "bqc6"
    assert issue["source_game_no"] == 98
    assert issue["sale_start_time"] == "2021-06-02 20:00:00"
    assert issue["matches"][1]["home_team_name"] == "主队2"
    assert issue["matches"][1]["source_raw_json"]["notice_evidence"]["home"] == "待定"
    assert issue["matches"][0]["source_full_home_goals"] is None
    assert issue["matches"][0]["source_product_result_code"] == "*,*"
    assert issue["matches"][0]["match_id"] is None
    assert issue["matches"][0]["fixture_id"] is None
    assert issue["raw_json"]["import_receipt"]["manifest_sha256"] == batch["manifest_sha256"]


def test_import_plan_rejects_preview_digest_mismatch(tmp_path: Path) -> None:
    preview, manifest, summary = _write_inputs(tmp_path)
    preview.write_text(preview.read_text(encoding="utf-8-sig") + "\n", encoding="utf-8-sig")

    with pytest.raises(ValueError, match="preview SHA-256"):
        load_issue_batch(preview, manifest, summary, offset=0, limit=10)


def test_import_plan_rejects_manifest_digest_mismatch(tmp_path: Path) -> None:
    preview, manifest, summary = _write_inputs(tmp_path)
    manifest.write_text(
        manifest.read_text(encoding="utf-8-sig").replace("candidate_new_issue", "blocked_review"),
        encoding="utf-8-sig",
    )

    with pytest.raises(ValueError, match="manifest SHA-256"):
        load_issue_batch(preview, manifest, summary, offset=0, limit=10)


def test_import_cli_defaults_to_latest_api_complete_snapshot() -> None:
    from scripts.traditional_history_import import default_input_paths

    preview, manifest, summary = default_input_paths()

    assert preview.name == "TRADITIONAL-HISTORY-IMPORT-PREVIEW-API-COMPLETE-20261101.csv"
    assert manifest.name == "TRADITIONAL-HISTORY-IMPORT-MANIFEST-API-COMPLETE-20261101.csv"
    assert summary.name == "TRADITIONAL-HISTORY-IMPORT-MANIFEST-API-COMPLETE-20261101.json"


def test_legacy_type_repair_rejects_old_partial_snapshot_contract() -> None:
    from scripts.traditional_history_type_repair import _validate_plan

    with pytest.raises(ValueError, match="unsupported legacy issue repair contract"):
        _validate_plan({"contract": "sporttery-legacy-pool-issue-type-repair/v1"})


def test_legacy_type_repair_matches_actual_kickoff_across_business_day_boundary() -> None:
    from scripts.traditional_history_type_repair import _verify_official_match_rows

    class Cursor:
        rows: list[tuple[object, ...]]

        def execute(self, query: str, params: tuple[list[int]]) -> None:
            assert params == ([701],)
            self.rows = (
                [(701, "主队", "客队", "2026-10-27", "2026-10-26")]
                if "kickoff_time" in query
                else [(701, "主队", "客队", "2026-10-26")]
            )

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.rows

    member = {
        "match_id": 701,
        "home_team_name": "主队",
        "away_team_name": "客队",
        "kickoff_date": None,
        "kickoff_time": "2026-10-27 00:00:00",
    }

    _verify_official_match_rows(Cursor(), "26127", [member])


def test_legacy_type_repair_rejects_business_date_when_actual_kickoff_date_differs() -> None:
    from scripts.traditional_history_type_repair import _verify_official_match_rows

    class Cursor:
        rows = [(701, "主队", "客队", "2026-10-28", "2026-10-27")]

        def execute(self, query: str, params: tuple[list[int]]) -> None:
            assert "kickoff_time" in query
            assert params == ([701],)

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.rows

    member = {
        "match_id": 701,
        "home_team_name": "主队",
        "away_team_name": "客队",
        "kickoff_date": None,
        "kickoff_time": "2026-10-27 00:00:00",
    }

    with pytest.raises(ValueError, match="official-match link differs from its slot identity"):
        _verify_official_match_rows(Cursor(), "26127", [member])


def test_apply_target_must_be_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://fqp:secret@db.example.invalid:5432/fqp")
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("PGSERVICE", raising=False)
    monkeypatch.delenv("PGSERVICEFILE", raising=False)

    with pytest.raises(ValueError, match="loopback or local PostgreSQL socket"):
        _local_database_parameters()


def test_apply_target_pins_loopback_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://fqp:secret@localhost:5432/fqp")
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("PGSERVICE", raising=False)
    monkeypatch.delenv("PGSERVICEFILE", raising=False)

    params = _local_database_parameters()

    assert params["hostaddr"] == "127.0.0.1"
    assert params["connect_timeout"] == "5"


def test_apply_target_rejects_postgres_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://fqp:secret@127.0.0.1:5432/fqp")
    monkeypatch.setenv("PGOPTIONS", "-c search_path=other")
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("PGSERVICE", raising=False)
    monkeypatch.delenv("PGSERVICEFILE", raising=False)

    with pytest.raises(ValueError, match="service/hostaddr overrides"):
        _local_database_parameters()


def test_import_plan_can_select_exact_existing_issue_for_fill(tmp_path: Path) -> None:
    preview, manifest, summary = _write_inputs(
        tmp_path,
        readiness="candidate_fill_exact_existing_issue",
        production_state="existing_issue_matches_source_api",
    )

    batch = load_issue_batch(preview, manifest, summary, offset=0, limit=10, kind="fill")

    assert batch["issue_operation"] == "fill"
    assert batch["candidate_issue_count"] == 1
    assert batch["selected_member_count"] == 6
    member = batch["issues"][0]["matches"][0]
    existing = dict(member)
    existing.update(
        {
            "match_id": 8765,
            "fixture_id": 4321,
            "home_win_prob": 0.42,
            "kickoff_time": datetime(2021, 6, 5, 0, 0),
            "kickoff_date": None,
            "kickoff_time_precision": "unknown",
            "source_match_id": None,
            "source_full_home_goals": None,
            "source_full_away_goals": None,
            "source_half_home_goals": None,
            "source_half_away_goals": None,
            "source_product_result_code": None,
            "source_result_semantics_key": None,
            "source_result_source": None,
            "kickoff_evidence": {},
            "source_result_evidence": {},
            "source_raw_json": {"legacy": "preserve"},
        }
    )
    updates = _prepare_fill_member(existing, member)

    assert updates["kickoff_date"].isoformat() == "2021-06-05"
    assert updates["kickoff_time_precision"] == "date_only"
    assert updates["source_match_id"] == member["source_match_id"]
    assert "kickoff_time" not in updates
    assert "match_id" not in updates
    assert "fixture_id" not in updates
    assert "home_win_prob" not in updates
    assert updates["source_raw_json"]["legacy"] == "preserve"


def test_fill_plan_rejects_any_non_exact_production_slot(tmp_path: Path) -> None:
    preview, manifest, summary = _write_inputs(
        tmp_path,
        readiness="candidate_fill_exact_existing_issue",
        production_state="existing_issue_matches_source_api",
        exact_slots=False,
    )

    with pytest.raises(ValueError, match="non-exact existing production slot"):
        load_issue_batch(preview, manifest, summary, kind="fill")


def test_fill_rejects_live_team_or_date_drift(tmp_path: Path) -> None:
    preview, manifest, summary = _write_inputs(
        tmp_path,
        readiness="candidate_fill_exact_existing_issue",
        production_state="existing_issue_matches_source_api",
    )
    source = load_issue_batch(preview, manifest, summary, kind="fill")["issues"][0]["matches"][0]
    existing = dict(source)
    existing["away_team_name"] = "另一支球队"

    with pytest.raises(ValueError, match="away team differs"):
        _prepare_fill_member(existing, source)


def _live_draw_fill_header(source_namespace: str = "sporttery_live_draw"):
    raw = {"source": "sporttery_live_draw", "legacy_capture": "retain"}
    existing = {
        "id": 812,
        "game_type": "bqc6",
        "issue_no": "26218",
        "source_game_type": "bqc6",
        "source_game_no": 98,
        "source_game_no_source": source_namespace,
        "sale_start_time": "2026-10-28 20:00:00",
        "sale_stop_time": "2026-11-01 21:30:00",
        "total_matches": 6,
        "official_status": "closed",
        "prize_pool_estimate": None,
        "raw_json": raw,
        "raw_hash": _pool_raw_hash(raw),
    }
    issue = {
        "game_type": "bqc6",
        "issue_no": "26218",
        "source_game_type": "bqc6",
        "source_game_no": 98,
        "source_game_no_source": "sporttery_history_api",
        "sale_start_time": "2026-10-28 20:00:00",
        "sale_stop_time": "2026-11-01 21:30:00",
        "total_matches": 6,
        "raw_json": {
            "source": "sporttery_history_api",
            "import_receipt": {"contract": "sporttery-traditional-history-import/v1"},
        },
    }
    return existing, issue


def test_fill_accepts_same_game_no_live_source_and_preserves_its_namespace() -> None:
    existing, issue = _live_draw_fill_header()

    updates = _prepare_fill_header(existing, issue)

    assert "source_game_no_source" not in updates
    marker = updates["raw_json"]["traditional_history_import"]
    assert marker["evidence"]["source"] == "sporttery_history_api"
    assert marker["receipt"] == issue["raw_json"]["import_receipt"]
    assert marker["header_state_sha256"]
    assert updates["raw_json"]["source"] == "sporttery_live_draw"
    assert updates["raw_json"]["legacy_capture"] == "retain"


def test_fill_rejects_unrecognized_existing_source_namespace() -> None:
    existing, issue = _live_draw_fill_header("unreviewed_source")

    with pytest.raises(ValueError, match="source_game_no_source conflicts"):
        _prepare_fill_header(existing, issue)


def test_fill_rejects_live_source_with_different_game_no() -> None:
    existing, issue = _live_draw_fill_header()
    issue["source_game_no"] = 90

    with pytest.raises(ValueError, match="source_game_no conflicts"):
        _prepare_fill_header(existing, issue)


def test_fill_rejects_live_source_without_a_known_game_no() -> None:
    existing, issue = _live_draw_fill_header()
    existing["source_game_no"] = None
    issue["source_game_no"] = None

    with pytest.raises(ValueError, match="source_game_no is missing"):
        _prepare_fill_header(existing, issue)


def test_fill_rejects_non_history_namespace_for_live_draw_source() -> None:
    existing, issue = _live_draw_fill_header()
    issue["source_game_no_source"] = "unreviewed_source"

    with pytest.raises(ValueError, match="source_game_no_source conflicts"):
        _prepare_fill_header(existing, issue)


def test_apply_rejects_unbounded_or_mixed_operation_batches_before_database_access() -> None:
    oversized = {
        "issue_operation": "new",
        "issues": [{"issue_operation": "new"}] * 101,
    }
    mixed = {
        "issue_operation": "fill",
        "issues": [{"issue_operation": "new"}],
    }

    with pytest.raises(ValueError, match="cannot exceed 100"):
        apply_issue_batch(None, oversized)
    with pytest.raises(ValueError, match="does not match"):
        apply_issue_batch(None, mixed)


def test_empty_fill_apply_reports_fill_counters_without_database_access() -> None:
    assert apply_issue_batch(None, {"issue_operation": "fill", "issues": []}) == {
        "filled_issues": 0,
        "filled_members": 0,
        "already_filled_issues": 0,
    }
