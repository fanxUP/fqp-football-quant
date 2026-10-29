from scripts.sources.titan007 import roster


def test_parse_transfers():
    text = """var transferInfo = [["2025-2026","25","365","2025-07-01","","利物浦","利物浦","布伦特福德","賓福特","1480",1,"Liverpool","Brentford"]];"""
    rows = roster.parse_transfers(text)
    assert rows[0]["from_team_id"] == 25
    assert rows[0]["to_team_id"] == 365
    assert rows[0]["transfer_date"] == "2025-07-01"
    assert rows[0]["fee"] == "1480"


def test_parse_coach():
    text = """var coach = [['887657','','米洛万·佩特洛维奇','米洛万·佩特洛维奇','Michael Petrovic',0]];"""
    coach = roster.parse_coach(text)
    assert coach["coach_player_id"] == 887657
    assert coach["coach_name"] == "米洛万·佩特洛维奇"
