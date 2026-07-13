from datetime import date

from scripts.jobs.refresh_official_seasons import (
    SeasonCandidate,
    iter_date_windows,
    normalize_match,
    select_season_window,
)


def test_started_current_season_is_filled_from_opening_day_through_today():
    selected = select_season_window(
        [
            SeasonCandidate(14355, "2026", date(2026, 4, 4), date(2026, 11, 30)),
            SeasonCandidate(13557, "2025", date(2025, 3, 29), date(2025, 11, 9)),
        ],
        today=date(2026, 7, 13),
    )

    assert selected.season_id == 14355
    assert selected.fetch_start == date(2026, 4, 4)
    assert selected.fetch_end == date(2026, 7, 13)
    assert selected.selection_reason == "current_started"


def test_not_started_current_season_uses_the_previous_complete_season():
    selected = select_season_window(
        [
            SeasonCandidate(15574, "2026/27", date(2026, 8, 15), date(2027, 5, 23)),
            SeasonCandidate(13419, "2025/26", date(2025, 8, 22), date(2026, 5, 16)),
        ],
        today=date(2026, 7, 13),
    )

    assert selected.season_id == 13419
    assert selected.fetch_start == date(2025, 8, 22)
    assert selected.fetch_end == date(2026, 5, 16)
    assert selected.selection_reason == "previous_complete"


def test_latest_finished_season_is_used_when_no_new_season_is_listed():
    selected = select_season_window(
        [SeasonCandidate(13419, "2025/26", date(2025, 8, 22), date(2026, 5, 16))],
        today=date(2026, 7, 13),
    )

    assert selected.fetch_start == date(2025, 8, 22)
    assert selected.fetch_end == date(2026, 5, 16)
    assert selected.selection_reason == "latest_complete"


def test_official_season_requests_use_inclusive_seven_day_windows():
    assert list(iter_date_windows(date(2026, 4, 4), date(2026, 4, 18))) == [
        (date(2026, 4, 4), date(2026, 4, 10)),
        (date(2026, 4, 11), date(2026, 4, 17)),
        (date(2026, 4, 18), date(2026, 4, 18)),
    ]


def test_normalize_match_preserves_official_fixture_identity_without_fake_ticket_code():
    normalized = normalize_match(
        {
            "uniformMatchId": 2339244,
            "gmMatchId": 0,
            "matchDate": "2026-04-04",
            "matchTime": "21:00",
            "homeAbbCnName": "代格福什",
            "awayAbbCnName": "天狼星",
            "uniformHomeTeamId": 1233,
            "uniformAwayTeamId": 312,
            "gameweek": "1",
            "phaseName": "Regular Season",
            "sectionsNo1": "0:0",
            "sectionsNo999": "0:3",
            "wbsjMatchSc": "Played",
            "wbsjMatchScDesc": "已完成",
        },
        uniform_league_id=1085,
        league_name="瑞典超级联赛",
        season_id=14355,
        season_name="2026",
    )

    assert normalized["uniform_match_id"] == 2339244
    assert normalized["gm_match_id"] is None
    assert normalized["official_match_code"] is None
    assert normalized["kickoff_time"].isoformat() == "2026-04-04T21:00:00"
    assert normalized["full_home_goals"] == 0
    assert normalized["full_away_goals"] == 3
    assert normalized["source_name"] == "sporttery"
