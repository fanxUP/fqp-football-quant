import json

from scripts.audit_official_history import (
    load_uniform_artifact_rows,
    select_in_scope_official_match_ids,
    summarize_official_artifact_coverage,
    summarize_official_history_rows,
)


def test_load_uniform_artifact_rows_keeps_response_rows_separate(tmp_path):
    artifact = tmp_path / "page.json"
    artifact.write_text(
        json.dumps(
            {
                "response": {
                    "value": {
                        "matchResult": [
                            {
                                "matchId": 123,
                                "matchNumStr": "周三001",
                                "matchDate": "2026-07-15",
                                "leagueAllName": "美国职业大联盟",
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    pages, rows = load_uniform_artifact_rows(tmp_path)

    assert pages == 1
    assert rows == [
        {
            "match_id": "123",
            "league_name": "美国职业大联盟",
            "business_date": "2026-07-15",
        }
    ]


def test_artifact_coverage_excludes_matches_outside_selected_event_seasons():
    selected, excluded = select_in_scope_official_match_ids(
        artifact_rows=[
            {
                "match_id": "old",
                "league_name": "美国职业大联盟",
                "business_date": "2025-07-01",
            },
            {
                "match_id": "current",
                "league_name": "美国职业大联盟",
                "business_date": "2026-07-01",
            },
        ],
        season_targets={
            "美国职业大联盟": ("2026-02-21", "2026-12-24"),
        },
        start_date="2025-01-01",
        end_date="2026-07-13",
    )

    assert selected == {"current"}
    assert excluded == 1


def test_artifact_coverage_keeps_requested_range_before_first_season_reconciliation():
    selected, excluded = select_in_scope_official_match_ids(
        artifact_rows=[
            {
                "match_id": "bootstrap",
                "league_name": "美国职业大联盟",
                "business_date": "2026-07-01",
            }
        ],
        season_targets={},
        start_date="2026-01-01",
        end_date="2026-07-13",
    )

    assert selected == {"bootstrap"}
    assert excluded == 0


def test_audit_separates_identity_integrity_from_source_completeness():
    rows = [
        {
            "business_date": "2026-07-10",
            "official_match_code": "周五098",
            "source_match_id": "2040374",
            "has_result": True,
            "home_team_name": "西班牙",
            "away_team_name": "比利时",
            "kickoff_time": "2026-07-11T03:00:00",
        },
        {
            "business_date": "2026-07-11",
            "official_match_code": "周五099",
            "source_match_id": None,
            "has_result": False,
            "home_team_name": "",
            "away_team_name": "英格兰",
            "kickoff_time": None,
        },
    ]

    audit = summarize_official_history_rows(rows, "2026-01-01", "2026-07-11")

    assert audit["matches"] == 2
    assert audit["matches_with_results"] == 1
    assert audit["matches_with_source_match_id"] == 1
    assert audit["weekday_mismatches"] == 1
    assert audit["missing_team_names"] == 1
    assert audit["missing_kickoff_time"] == 1
    assert audit["identity_integrity"] == "error"
    assert audit["source_completeness"] == "unverified_against_official_source"


def test_audit_marks_identity_integrity_ok_without_claiming_complete_coverage():
    rows = [
        {
            "business_date": "2026-07-10",
            "official_match_code": "周五098",
            "source_match_id": "2040374",
            "has_result": True,
            "home_team_name": "西班牙",
            "away_team_name": "比利时",
            "kickoff_time": "2026-07-11T03:00:00",
        }
    ]

    audit = summarize_official_history_rows(rows, "2026-01-01", "2026-07-11")

    assert audit["identity_integrity"] == "ok"
    assert audit["source_completeness"] == "unverified_against_official_source"


def test_artifact_coverage_is_verified_only_when_every_official_id_is_in_database():
    coverage = summarize_official_artifact_coverage(
        official_match_ids={"2040455", "2040456"},
        database_match_ids={"2040455", "2040456"},
        artifact_pages=2,
    )

    assert coverage == {
        "official_artifact_pages": 2,
        "official_distinct_match_ids": 2,
        "database_match_ids_present": 2,
        "missing_database_match_ids": 0,
        "source_completeness": "verified_against_official_artifacts",
    }


def test_artifact_coverage_reports_missing_official_ids():
    coverage = summarize_official_artifact_coverage(
        official_match_ids={"2040455", "2040456"},
        database_match_ids={"2040455"},
        artifact_pages=2,
    )

    assert coverage["missing_database_match_ids"] == 1
    assert coverage["source_completeness"] == "incomplete_against_official_artifacts"
