from scripts.jobs.seed_competitions import LEAGUE_MAP


def test_current_competitions_have_verified_team_counts():
    counts = {item["competition_name_cn"]: item["total_teams"] for item in LEAGUE_MAP}
    assert counts == {
        "挪威超级联赛": 16,
        "芬兰超级联赛": 12,
        "瑞典超级联赛": 16,
        "韩国职业联赛": 12,
        "世界杯": 48,
    }
