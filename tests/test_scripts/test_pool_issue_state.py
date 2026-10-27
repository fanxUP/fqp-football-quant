from datetime import UTC, datetime

from scripts.pool_issue_state import sale_window

NOW = datetime(2026, 10, 27, 4, tzinfo=UTC)


def test_draw_estimate_is_never_a_sales_cutoff():
    assert sale_window({"estimateDrawTime": "2026-10-27 20:00"}, now=NOW)["state"] == "unknown"


def test_window_requires_start_and_stop_consistency():
    assert (
        sale_window(
            {"saleStartTime": "2026-10-27 13:00", "saleEndTime": "2026-10-27 20:00"}, now=NOW
        )["state"]
        == "not_started"
    )
    assert (
        sale_window({"onSale": 1, "saleEndTime": "2026-10-27 11:00"}, now=NOW)["state"]
        == "conflict"
    )
    assert (
        sale_window({"onSale": 0, "saleEndTime": "2026-10-27 20:00"}, now=NOW)["state"]
        == "suspended"
    )
    assert (
        sale_window(
            {"saleEndTime": "2026-10-27 20:00", "lotterySaleEndTime": "2026-10-27 21:00"}, now=NOW
        )["state"]
        == "conflict"
    )
