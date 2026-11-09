from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
from unittest.mock import MagicMock, Mock

import pytest

from scripts import sporttery_pool_schedule
from scripts.sporttery_pool_schedule import SCHEDULE_GAMES, apply_match_head, parse_current_issue

NOW = datetime.fromisoformat("2026-11-12T20:20:00+08:00")


def schedule_response(code, count, issue_no="26163"):
    return {
        "errorCode": "0",
        "value": {
            "drawNumList": [issue_no],
            "drawMatch": {
                "lotteryGameNum": str(code),
                "lotteryDrawNum": issue_no,
                "lotterySaleBeginTime": "2026-11-08 20:00",
                "lotterySaleEndTime": "2026-11-12 22:00",
                "matchList": [
                    {
                        "matchNum": order,
                        "gmMatchId": 2042692 + order if order <= 6 else 0,
                        "matchName": "欧国联",
                        "leagueId": 127,
                        "startTime": "2026-11-13",
                        "masterTeamName": f"主{order}",
                        "guestTeamName": f"客{order}",
                        "masterTeamAllName": f"主队{order}",
                        "guestTeamAllName": f"客队{order}",
                    }
                    for order in range(1, count + 1)
                ],
            },
        },
    }


def match_head(**overrides):
    return {
        "sportteryMatchId": 2042693,
        "sportteryTournamentId": 127,
        "homeTeamShortName": "主1",
        "awayTeamShortName": "客队1",
        "matchDateTime": "2026-11-13 01:00",
        **overrides,
    }


@pytest.mark.parametrize("code,count", [(90, 14), (900129, 14), (98, 6), (94, 4)])
def test_official_current_four_games_are_distinct_from_draw_codes(code, count):
    issue = parse_current_issue(code, schedule_response(code, count), NOW)
    assert issue["game_type"] == SCHEDULE_GAMES[code][0]
    assert issue["total_matches"] == count
    assert issue["raw_json"]["lotteryGameNum"] == str(code)
    assert issue["sale_stop"] == "2026-11-12T22:00:00+08:00"
    assert issue["source_game_no"] is None
    assert issue["matches"][0]["kickoff_time"] is None
    assert issue["matches"][0]["kickoff_time_precision"] == "date_only"
    if count == 14:
        assert issue["matches"][7]["source_ids"] == {}


def test_partial_or_wrong_game_cannot_replace_an_existing_issue():
    data = schedule_response(90, 14)
    assert parse_current_issue(900129, data, NOW) is None
    data["value"]["drawMatch"]["matchList"][0]["matchNum"] = 2
    assert parse_current_issue(90, data, NOW) is None


def test_exact_kickoff_requires_official_id_competition_ordered_teams_and_local_date():
    member = parse_current_issue(90, schedule_response(90, 14), NOW)["matches"][0]
    for change in (
        {"sportteryMatchId": 2042692},
        {"sportteryTournamentId": 128},
        {"homeTeamShortName": "客1", "awayTeamShortName": "主1"},
        {"matchDateTime": "2026-11-14 01:00"},
        {"matchDateTime": "2026-11-13"},
    ):
        assert not apply_match_head(deepcopy(member), match_head(**change))
    assert apply_match_head(member, match_head())
    assert member["kickoff_time"] == "2026-11-13T01:00:00+08:00"
    assert member["kickoff_evidence"]["source"] == "sporttery_match_head"
    assert not apply_match_head(member, match_head(matchDateTime="2026-11-13 02:00"))


def test_parallel_issues_are_rotated_and_match_heads_shared(monkeypatch):
    def get_issue(code, issue):
        if code != 90:
            return {}
        selected = issue or "26163"
        payload = schedule_response(90, 14, selected)
        payload["value"]["drawNumList"] = ["26163", "26164", "26165", "26166"]
        return payload

    client = Mock()
    client.get_traditional_lottery_schedule.side_effect = get_issue
    client.get_match_head.return_value = {"value": {}}
    stored = []
    writer = Mock(side_effect=lambda conn, pool: (stored.append(pool["issue_no"]) or 1, 14))
    monkeypatch.setattr(sporttery_pool_schedule, "SportteryClient", lambda **kwargs: client)
    monkeypatch.setattr(sporttery_pool_schedule, "business_now", lambda: NOW)
    monkeypatch.setattr(sporttery_pool_schedule, "get_db", lambda: nullcontext(Mock()))
    monkeypatch.setattr(sporttery_pool_schedule, "_store_current_issue", writer)
    monkeypatch.setattr(sporttery_pool_schedule, "_heads", {})
    monkeypatch.setattr(sporttery_pool_schedule, "_issue_checks", {})

    first = sporttery_pool_schedule.refresh_current_pool_schedule()
    assert stored == ["26163", "26164", "26165"]
    assert first["head_requests"] == 6
    stored.clear()
    second = sporttery_pool_schedule.refresh_current_pool_schedule()
    assert stored == ["26163", "26166", "26164"]
    assert second["head_requests"] == 0


def test_pool_schedule_writer_bounds_only_the_shared_notice_lock_wait(monkeypatch):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = ("2s",)
    cur.fetchall.return_value = []
    monkeypatch.setattr(sporttery_pool_schedule, "store_pool_issue", lambda *_args, **_kwargs: 7)

    changed = sporttery_pool_schedule._store_current_issue(
        conn,
        {
            "game_type": "t14c",
            "issue_no": "26163",
            "raw_json": {"schedule": "fixture"},
            "official_status": "scheduled",
            "matches": [],
        },
    )

    assert changed == (1, 0)
    queries = [call.args[0] for call in cur.execute.call_args_list]
    notice_lock = "SELECT pg_advisory_xact_lock(%s, %s)"
    identity_lock = "SELECT pg_advisory_xact_lock(%s)"
    assert queries.index("SELECT current_setting('lock_timeout')") < queries.index(notice_lock)
    assert queries.index(notice_lock) < queries.index(identity_lock)
    timeout_updates = [
        call.args
        for call in cur.execute.call_args_list
        if "set_config('lock_timeout'" in call.args[0]
    ]
    assert timeout_updates == [
        ("SELECT set_config('lock_timeout', %s, true)", ("45s",)),
        ("SELECT set_config('lock_timeout', %s, true)", ("2s",)),
    ]
