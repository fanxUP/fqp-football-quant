from scripts.upset.reports import render_markdown, validate_period


def test_report_period_must_be_ordered():
    assert validate_period("2026-07-01", "2026-07-31") == (
        "2026-07-01",
        "2026-07-31",
    )


def test_report_markdown_separates_user_and_agent_funds():
    markdown = render_markdown(
        "daily",
        "2026-07-21",
        "2026-07-21",
        {
            "upsets": {"count": 2, "severe_count": 1, "rate": 0.1},
            "user": {"stake": 100, "prize": 150, "profit": 50, "roi": 0.5},
            "agent": {"stake": 500, "prize": 400, "profit": -100, "roi": -0.2},
            "cold_impact": {"user_profit": 30, "agent_profit": -50},
            "by_level": {"A": 1, "B": 1},
            "by_play": {"spf": 2},
            "by_league": [{"league": "测试联赛", "count": 2}],
            "model_quality": {"sample_size": 3, "brier": 0.22, "log_loss": 0.7},
        },
    )

    assert "用户实票" in markdown
    assert "Agent虚拟投注" in markdown
    assert "¥100.00" in markdown
    assert "¥500.00" in markdown
