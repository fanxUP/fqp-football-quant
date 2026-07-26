from scripts.jobs.collect_injury_data import _extract_injury_fields


def test_extracts_current_fixture_injury_fields_from_player_payload():
    status, injury_type, reason = _extract_injury_fields(
        {
            "player": {
                "type": "Missing Fixture",
                "reason": "Back Bruise",
            }
        }
    )

    assert status == "injured"
    assert injury_type == "Missing Fixture"
    assert reason == "Back Bruise"


def test_marks_suspension_as_suspended():
    status, injury_type, reason = _extract_injury_fields(
        {"player": {"type": "Suspended", "reason": "Red Card"}}
    )

    assert status == "suspended"
    assert injury_type == "Suspended"
    assert reason == "Red Card"
