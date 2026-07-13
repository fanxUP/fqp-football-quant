from unittest.mock import patch

from apps.backend.src.routers.simulator import _pool_capabilities


def test_simulator_matches_filters_to_future_sellable_statuses(client):
    with patch("apps.backend.src.routers.simulator.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [(1, "2026-07-10", "世界杯", "西班牙", "比利时", "2026-07-11T03:00:00", "scheduled", "周五098")],
            [],
        ]

        response = client.get("/api/simulator/matches?date=2026-07-10")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    sql = cursor.execute.call_args_list[0].args[0]
    assert "sale_status = 'selling'" in sql
    assert "LOWER(COALESCE(m.match_status, '')) IN ('scheduled', 'selling', 'not_started')" in sql
    assert "m.kickoff_time > CURRENT_TIMESTAMP" in sql
    assert "m.sale_stop_time IS NULL OR m.sale_stop_time > CURRENT_TIMESTAMP" in sql


def test_pool_capabilities_support_current_sporttery_field_names():
    capabilities = _pool_capabilities({
        "poolList": [
            {"poolCode": "HAD", "cbtSingle": 0, "cbtAllUp": 1},
            {"poolCode": "CRS", "cbtSingle": 1, "cbtAllUp": 1},
            {"poolCode": "TTG", "intSingle": 1, "intAllUp": 0},
        ],
    })

    assert capabilities["spf"] == {"single": False, "pass": True}
    assert capabilities["bf"] == {"single": True, "pass": True}
    assert capabilities["zjq"] == {"single": True, "pass": False}


def test_simulator_matches_orders_official_had_options_home_draw_away(client):
    raw = {"poolList": [{"poolCode": "HAD", "cbtSingle": 0, "cbtAllUp": 1}]}
    with patch("apps.backend.src.routers.simulator.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [(1, "2026-07-12", "挪超", "主队", "客队", "2026-07-13T03:00:00", "scheduled", "周日213", raw)],
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
            [(1, "2026-07-12", "挪超", "主队", "客队", "2026-07-13T03:00:00", "scheduled", "周日213", {})],
            [(1, "spf", "h", "主胜", 2.1, None, False)],
        ]

        response = client.get("/api/simulator/matches")

    assert response.status_code == 200
    spf = response.json()["matches"][0]["odds"]["spf"]
    assert spf["options"]
    assert spf["is_single_allowed"] is False
    assert spf["is_pass_allowed"] is False


def test_pool_capabilities_do_not_infer_permission_from_value_fields():
    capabilities = _pool_capabilities({
        "poolList": [{
            "poolCode": "HAD",
            "poolStatus": "Selling",
            "cbtSingle": 0,
            "cbtAllUp": 0,
            "cbtValue": 2,
            "intSingle": 0,
            "intAllUp": 0,
            "intValue": 2,
        }],
    })

    assert capabilities["spf"] == {"single": False, "pass": False}
