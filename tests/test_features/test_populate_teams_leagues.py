from scripts.features.populate_teams_leagues import _infer_country


def test_infer_country_covers_current_official_leagues():
    assert _infer_country("Brann", "挪威超级联赛") == "Norway"
    assert _infer_country("HJK", "芬兰超级联赛") == "Finland"
    assert _infer_country("울산", "韩国职业联赛") == "South Korea"
    assert _infer_country("阿根廷", "世界杯") == "Argentina"
