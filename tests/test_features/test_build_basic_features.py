from datetime import datetime

from scripts.features.build_basic_features import compute_rest_days, compute_team_form


def test_team_form_uses_verified_sporttery_aliases_for_team_identity(mock_conn):
    conn, cur = mock_conn
    cur.fetchall.return_value = [
        (True, 2, 1, datetime(2025, 7, 1, 8, 0)),
    ]

    form = compute_team_form(
        "亚特兰大联",
        "2026-07-18T08:10:00",
        last_n=10,
        conn=conn,
        team_id=1360,
    )

    assert form["matches_played"] == 1
    assert form["wins"] == 1
    assert form["goals_for"] == 2
    assert form["goals_against"] == 1
    assert cur.execute.call_args.args[1]["team_id"] == 1360
    assert "team_aliases" in cur.execute.call_args.args[0]


def test_rest_days_uses_verified_sporttery_aliases_for_team_identity(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = (datetime(2026, 7, 10, 8, 0),)

    rest_days = compute_rest_days(
        "亚特兰大联",
        "2026-07-18T08:10:00",
        conn,
        team_id=1360,
    )

    assert rest_days == 8
    assert cur.execute.call_args.args[1]["team_id"] == 1360
    assert "team_aliases" in cur.execute.call_args.args[0]
