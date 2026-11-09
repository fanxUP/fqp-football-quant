from pathlib import Path

from scripts.player_identity_candidates import build_candidate_rows
from scripts.player_identity_candidates import main as candidate_main


def test_exact_name_and_birthdate_remain_manual_candidates():
    rows = build_candidate_rows(
        [
            {
                "source_name": "titan007",
                "external_player_id": "20",
                "player_name": " José  Silva ",
                "birth_date": "1999-02-03",
                "evidence_ref": "titan007:player:20",
            }
        ],
        [
            {
                "player_id": "9",
                "player_name": "José Silva",
                "birth_date": "1999-02-03",
            }
        ],
    )

    assert rows == [
        {
            "source_name": "titan007",
            "external_player_id": "20",
            "source_player_name": "José Silva",
            "source_birth_date": "1999-02-03",
            "evidence_ref": "titan007:player:20",
            "candidate_player_id": "9",
            "candidate_player_name": "José Silva",
            "candidate_birth_date": "1999-02-03",
            "match_basis": "exact_name_and_birth_date",
            "candidate_count": 1,
            "mapping_status": "candidate",
            "requires_manual_review": True,
        }
    ]


def test_duplicate_exact_candidates_are_reported_as_ambiguous():
    rows = build_candidate_rows(
        [
            {
                "source_name": "titan007",
                "external_player_id": "20",
                "player_name": "Alex Lee",
                "birth_date": "2000-01-01",
                "evidence_ref": "source-row:20",
            }
        ],
        [
            {"player_id": "9", "player_name": "Alex Lee", "birth_date": "2000-01-01"},
            {"player_id": "3", "player_name": "Alex Lee", "birth_date": "2000-01-01"},
        ],
    )

    assert [row["candidate_player_id"] for row in rows] == ["3", "9"]
    assert {row["candidate_count"] for row in rows} == {2}
    assert {row["match_basis"] for row in rows} == {"ambiguous_exact_name_and_birth_date"}
    assert {row["mapping_status"] for row in rows} == {"unresolved"}
    assert all(row["requires_manual_review"] for row in rows)


def test_name_only_match_is_not_treated_as_verified_or_birthdate_match():
    rows = build_candidate_rows(
        [
            {
                "source_name": "titan007",
                "external_player_id": "20",
                "player_name": "Sam Example",
                "birth_date": "",
                "evidence_ref": "source-row:20",
            }
        ],
        [{"player_id": "9", "player_name": "Sam Example", "birth_date": "1990-01-02"}],
    )

    assert rows[0]["match_basis"] == "exact_name_birth_date_missing"
    assert rows[0]["mapping_status"] == "candidate"
    assert rows[0]["requires_manual_review"] is True


def test_birthdate_conflict_stays_unresolved():
    rows = build_candidate_rows(
        [
            {
                "source_name": "titan007",
                "external_player_id": "20",
                "player_name": "Sam Example",
                "birth_date": "1990-01-02",
                "evidence_ref": "source-row:20",
            }
        ],
        [{"player_id": "9", "player_name": "Sam Example", "birth_date": "1992-04-05"}],
    )

    assert rows[0]["candidate_player_id"] == "9"
    assert rows[0]["match_basis"] == "birth_date_conflict"
    assert rows[0]["mapping_status"] == "unresolved"
    assert rows[0]["requires_manual_review"] is True


def test_no_exact_name_is_explicitly_unresolved():
    rows = build_candidate_rows(
        [
            {
                "source_name": "titan007",
                "external_player_id": "20",
                "player_name": "First Name",
                "birth_date": "1990-01-02",
                "evidence_ref": "source-row:20",
            }
        ],
        [{"player_id": "9", "player_name": "Different Name", "birth_date": "1990-01-02"}],
    )

    assert rows == [
        {
            "source_name": "titan007",
            "external_player_id": "20",
            "source_player_name": "First Name",
            "source_birth_date": "1990-01-02",
            "evidence_ref": "source-row:20",
            "candidate_player_id": "",
            "candidate_player_name": "",
            "candidate_birth_date": "",
            "match_basis": "no_exact_name_candidate",
            "candidate_count": 0,
            "mapping_status": "unresolved",
            "requires_manual_review": True,
        }
    ]


def test_candidate_report_order_is_deterministic():
    source = [
        {
            "source_name": "titan007",
            "external_player_id": "2",
            "player_name": "Name B",
            "birth_date": "2000-01-01",
            "evidence_ref": "row:2",
        },
        {
            "source_name": "titan007",
            "external_player_id": "1",
            "player_name": "Name A",
            "birth_date": "2000-01-01",
            "evidence_ref": "row:1",
        },
    ]
    canonical = [
        {"player_id": "20", "player_name": "Name B", "birth_date": "2000-01-01"},
        {"player_id": "10", "player_name": "Name A", "birth_date": "2000-01-01"},
    ]

    first = build_candidate_rows(source, canonical)
    second = build_candidate_rows(list(reversed(source)), list(reversed(canonical)))

    assert first == second
    assert [row["external_player_id"] for row in first] == ["1", "2"]


def test_csv_command_writes_reproducible_file_only_report(tmp_path: Path):
    source = tmp_path / "source.csv"
    canonical = tmp_path / "canonical.csv"
    first_output = tmp_path / "first.csv"
    second_output = tmp_path / "second.csv"
    source.write_text(
        "source_name,external_player_id,player_name,birth_date,evidence_ref\n"
        "titan007,20,Example Player,1999-02-03,source-row:20\n",
        encoding="utf-8",
    )
    canonical.write_text(
        "player_id,player_name,birth_date\n9,Example Player,1999-02-03\n",
        encoding="utf-8",
    )

    for output in (first_output, second_output):
        assert (
            candidate_main(
                [
                    "--source-csv",
                    str(source),
                    "--canonical-csv",
                    str(canonical),
                    "--output-csv",
                    str(output),
                ]
            )
            == 0
        )

    assert first_output.read_bytes() == second_output.read_bytes()
    assert b"candidate,True" in first_output.read_bytes()
