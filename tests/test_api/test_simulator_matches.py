from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from apps.backend.src.routers.simulator import _pool_capabilities
from scripts.sporttery_sales import get_sporttery_sales_window

REST_WINDOW = get_sporttery_sales_window(
    datetime(2026, 7, 19, 2, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
)
OPEN_WINDOW = get_sporttery_sales_window(
    datetime(2026, 7, 18, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
)


@pytest.fixture(autouse=True)
def open_official_sales_window():
    with patch(
        "apps.backend.src.routers.simulator.get_sporttery_sales_window",
        return_value=OPEN_WINDOW,
    ):
        yield


def test_simulator_shows_future_official_matches_during_rest_even_without_current_odds(client):
    with (
        patch("apps.backend.src.routers.simulator.get_db") as get_db,
        patch(
            "apps.backend.src.routers.simulator.get_sporttery_sales_window",
            return_value=REST_WINDOW,
        ),
    ):
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [
                (
                    1,
                    "2026-07-19",
                    "英超",
                    "主队甲",
                    "客队甲",
                    "2026-07-19T21:00:00",
                    "scheduled",
                    "周日001",
                    {},
                    True,
                ),
                (
                    2,
                    "2026-07-20",
                    "英超",
                    "主队乙",
                    "客队乙",
                    "2026-07-20T21:00:00",
                    "scheduled",
                    "周一001",
                    {},
                    True,
                ),
            ],
            [(1, "spf", "h", "主胜", 2.1, None, True)],
        ]
        response = client.get("/api/simulator/matches")

    assert response.status_code == 200
    data = response.json()
    assert data["sales_window"] == REST_WINDOW.as_dict()
    assert data["total"] == 2
    first, second = data["matches"]
    assert first["match_num_str"] == "周日001"
    assert first["odds"]["spf"]["options"][0]["sp_value"] == 2.1
    assert second["match_num_str"] == "周一001"
    assert second["odds"]["spf"]["options"] == []


def test_manual_ticket_submission_is_rejected_during_official_rest_time(client):
    payload = {
        "source": "real-user",
        "play_type": "spf",
        "pass_type": "single",
        "multiple": 1,
        "items": [
            {
                "match_id": 22057,
                "play_type": "spf",
                "option_code": "h",
                "option_name": "主胜",
                "sp_value": 1.68,
            }
        ],
    }
    with patch(
        "apps.backend.src.routers.betting.get_sporttery_sales_window",
        return_value=REST_WINDOW,
    ):
        response = client.post("/api/v1/betting/tickets", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == REST_WINDOW.message


def test_simulator_ticket_submission_is_rejected_during_official_rest_time(client):
    payload = {
        "play_type": "spf",
        "pass_type": "single",
        "multiple": 1,
        "items": [
            {
                "match_id": 22057,
                "play_type": "spf",
                "option_code": "h",
                "option_name": "主胜",
                "sp_value": 1.68,
            }
        ],
    }
    with patch(
        "apps.backend.src.routers.simulator.get_sporttery_sales_window",
        return_value=REST_WINDOW,
    ):
        response = client.post("/api/simulator/tickets", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == REST_WINDOW.message


def test_simulator_matches_filters_to_future_sellable_statuses(client):
    with patch("apps.backend.src.routers.simulator.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [
                (
                    1,
                    "2026-07-10",
                    "世界杯",
                    "西班牙",
                    "比利时",
                    "2026-07-11T03:00:00",
                    "scheduled",
                    "周五098",
                    {},
                    False,
                )
            ],
            [],
        ]

        response = client.get("/api/simulator/matches?date=2026-07-10")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    sql = cursor.execute.call_args_list[0].args[0]
    assert "sale_status = 'selling'" in sql
    assert "LOWER(COALESCE(m.match_status, '')) IN ('scheduled', 'selling', 'not_started')" in sql
    assert "m.kickoff_time > %(now)s" in sql
    assert "(m.sale_stop_time IS NULL OR m.sale_stop_time > %(now)s)" in sql
    assert "m.updated_at BETWEEN %(status_since)s AND %(utc_now)s" in sql
    assert "m.raw_json->>'sellStatus' = '1'" in sql
    params = cursor.execute.call_args_list[0].args[1]
    assert params["now"] == datetime(2026, 7, 18, 12, 0)
    assert params["utc_now"] == datetime(2026, 7, 18, 4, 0)
    assert params["status_since"] == datetime(2026, 7, 18, 3, 40)


def test_simulator_matches_without_cutoff_require_fresh_official_status_and_odds(client):
    def match(match_id, day, code, kickoff):
        return (match_id, day, "英锦标赛", "主队", "客队", kickoff, "scheduled", code, {}, True)

    with patch("apps.backend.src.routers.simulator.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [
                match(1, "2026-07-18", "周六001", "2026-07-19T03:00:00"),
                match(2, "2026-07-19", "周日001", "2026-07-20T03:00:00"),
            ],
            [(2, "spf", "h", "主胜", 2.1, None, True)],
        ]

        response = client.get("/api/simulator/matches")

    assert response.status_code == 200
    assert [match["match_num_str"] for match in response.json()["matches"]] == ["周日001"]
    assert response.json()["matches"][0]["odds"]["spf"]["is_single_allowed"] is True
    odds_sql, params = cursor.execute.call_args_list[1].args
    assert "s.snapshot_time BETWEEN %(odds_since)s AND %(now)s" in odds_sql
    assert "pool->>'poolStatus' = 'Selling'" in odds_sql
    assert "jsonb_path_exists" in odds_sql
    assert params["odds_since"] == datetime(2026, 7, 18, 11, 25)


def test_pool_capabilities_support_current_sporttery_field_names():
    capabilities = _pool_capabilities(
        {
            "poolList": [
                {"poolCode": "HAD", "cbtSingle": 0, "cbtAllUp": 1},
                {"poolCode": "CRS", "cbtSingle": 1, "cbtAllUp": 1},
                {"poolCode": "TTG", "intSingle": 1, "intAllUp": 0},
            ],
        }
    )

    assert capabilities["spf"] == {"single": False, "pass": True}
    assert capabilities["bf"] == {"single": True, "pass": True}
    assert capabilities["zjq"] == {"single": True, "pass": False}


def test_simulator_matches_orders_official_had_options_home_draw_away(client):
    raw = {"poolList": [{"poolCode": "HAD", "cbtSingle": 0, "cbtAllUp": 1}]}
    with patch("apps.backend.src.routers.simulator.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [
                (
                    1,
                    "2026-07-12",
                    "挪超",
                    "主队",
                    "客队",
                    "2026-07-13T03:00:00",
                    "scheduled",
                    "周日213",
                    raw,
                    False,
                )
            ],
            [
                (1, "spf", "a", "客胜", 3.2, None, False),
                (1, "spf", "d", "平", 3.1, None, False),
                (1, "spf", "h", "主胜", 2.1, None, False),
            ],
        ]

        response = client.get("/api/simulator/matches")

    assert response.status_code == 200
    spf = response.json()["matches"][0]["odds"]["spf"]
    assert [option["option_code"] for option in spf["options"]] == ["h", "d", "a"]
    assert spf["is_pass_allowed"] is True


def test_simulator_matches_default_to_unavailable_when_pool_capability_is_missing(client):
    with patch("apps.backend.src.routers.simulator.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [
                (
                    1,
                    "2026-07-12",
                    "挪超",
                    "主队",
                    "客队",
                    "2026-07-13T03:00:00",
                    "scheduled",
                    "周日213",
                    {},
                    False,
                )
            ],
            [(1, "spf", "h", "主胜", 2.1, None, False)],
        ]

        response = client.get("/api/simulator/matches")

    assert response.status_code == 200
    spf = response.json()["matches"][0]["odds"]["spf"]
    assert spf["options"]
    assert spf["is_single_allowed"] is False
    assert spf["is_pass_allowed"] is False


def test_pool_capabilities_do_not_infer_permission_from_value_fields():
    capabilities = _pool_capabilities(
        {
            "poolList": [
                {
                    "poolCode": "HAD",
                    "poolStatus": "Selling",
                    "cbtSingle": 0,
                    "cbtAllUp": 0,
                    "cbtValue": 2,
                    "intSingle": 0,
                    "intAllUp": 0,
                    "intValue": 2,
                }
            ],
        }
    )

    assert capabilities["spf"] == {"single": False, "pass": False}
