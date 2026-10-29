from scripts.sources.titan007 import classify


def test_top_league_priority_and_tier():
    item = classify.classify_league(36, "英格兰超级联赛")
    assert item["region"] == "欧洲"
    assert item["country"] == "英格兰"
    assert item["type"] == "league"
    assert item["tier"] == 1
    assert item["priority"] == "S"


def test_women_youth_world_cup():
    item = classify.classify_league(730, "女子U17世界杯")
    assert item["audience"] == "women_youth"
    assert item["type"] == "cup"
    assert item["region"] == "国际"
    assert item["country"] == "国际"
    assert item["priority"] == "C"


def test_lower_spanish_league():
    item = classify.classify_league(951, "西班牙丁组联赛")
    assert item["country"] == "西班牙"
    assert item["tier"] == 4
    assert item["priority"] == "C"


def test_short_name_and_tournament():
    item = classify.classify_league(2167, "葡女锦")
    assert item["country"] == "葡萄牙"
    assert item["type"] == "tournament"
    assert item["audience"] == "women"


def test_saudi_pro_league_tier():
    item = classify.classify_league(292, "沙特阿拉伯职业联赛")
    assert item["country"] == "沙特阿拉伯"
    assert item["tier"] == 1


def test_continental_cup_country():
    item = classify.classify_league(89, "南美解放者杯")
    assert item["region"] == "南美"
    assert item["country"] == "国际"
    assert item["type"] == "cup"
