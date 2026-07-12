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
