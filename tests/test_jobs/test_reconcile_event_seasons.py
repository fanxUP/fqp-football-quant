from datetime import date

from scripts.jobs.reconcile_event_seasons import (
    MANUAL_SEASON_CANDIDATES,
    OFFICIAL_LEAGUE_REFS,
    SeasonCandidate,
    aggregate_selected_windows,
    select_season_window,
)


def test_started_current_season_is_selected_from_its_opening_day():
    selected = select_season_window(
        [
            SeasonCandidate(14355, "2026", date(2026, 4, 4), date(2026, 11, 30)),
            SeasonCandidate(12757, "2025", date(2025, 3, 29), date(2025, 11, 9)),
        ],
        today=date(2026, 7, 13),
    )

    assert selected.season_name == "2026"
    assert selected.start_date == date(2026, 4, 4)
    assert selected.end_date == date(2026, 11, 30)
    assert selected.selection_reason == "current_started"


def test_not_started_current_season_selects_previous_complete_season():
    selected = select_season_window(
        [
            SeasonCandidate(15500, "2026/2027", date(2026, 8, 15), date(2027, 5, 23)),
            SeasonCandidate(13419, "2025/2026", date(2025, 8, 22), date(2026, 5, 25)),
        ],
        today=date(2026, 7, 13),
    )

    assert selected.season_name == "2025/2026"
    assert selected.start_date == date(2025, 8, 22)
    assert selected.end_date == date(2026, 5, 25)
    assert selected.selection_reason == "previous_complete"


def test_same_cycle_from_multiple_official_regions_uses_union_window():
    selected = aggregate_selected_windows(
        [
            select_season_window(
                [SeasonCandidate(1, "2026", date(2023, 9, 7), date(2025, 9, 9))],
                today=date(2026, 7, 13),
            ),
            select_season_window(
                [SeasonCandidate(2, "2026", date(2025, 3, 17), date(2026, 3, 31))],
                today=date(2026, 7, 13),
            ),
        ]
    )

    assert selected.season_name == "2026"
    assert selected.start_date == date(2023, 9, 7)
    assert selected.end_date == date(2026, 3, 31)


def test_current_database_leagues_all_have_a_season_boundary_source():
    current_leagues = {
        "CONCACAF Nations League",
        "FFA Cup",
        "U20世界杯",
        "U23亚洲杯",
        "世界杯",
        "世界杯预选赛",
        "东亚锦标赛",
        "中北美金杯赛",
        "亚洲冠军乙级联赛",
        "亚洲冠军精英联赛",
        "俱乐部世界杯",
        "南美解放者杯",
        "国际赛",
        "女足东亚锦标赛",
        "女足世界杯",
        "女足亚洲杯",
        "巴西甲级联赛",
        "德国乙级联赛",
        "德国杯",
        "德国甲级联赛",
        "德国超级杯",
        "意大利杯",
        "意大利甲级联赛",
        "意大利超级杯",
        "挪威超级联赛",
        "日本乙级联赛",
        "日本天皇杯",
        "日本职业联赛",
        "日本联赛杯",
        "杯赛",
        "欧洲冠军联赛",
        "欧洲协会联赛",
        "欧洲超级杯",
        "欧罗巴联赛",
        "沙特职业联赛",
        "法国乙级联赛",
        "法国杯",
        "法国甲级联赛",
        "澳大利亚超级联赛",
        "瑞典超级联赛",
        "美国职业大联盟",
        "芬兰超级联赛",
        "英格兰冠军联赛",
        "英格兰甲级联赛",
        "英格兰社区盾杯",
        "英格兰联赛杯",
        "英格兰超级联赛",
        "英格兰足总杯",
        "英格兰锦标赛",
        "荷兰乙级联赛",
        "荷兰杯",
        "荷兰甲级联赛",
        "葡萄牙超级联赛",
        "西班牙国王杯",
        "西班牙甲级联赛",
        "西班牙超级杯",
        "非洲杯",
        "韩国杯",
        "韩国职业联赛",
        "中北美冠军杯",
        "亚洲杯",
        "亚运会女足",
        "亚运会男足",
        "俄罗斯超级联赛",
        "奥运会女足",
        "奥运会男足",
        "巴西杯",
        "挪威杯",
        "欧洲U21锦标赛",
        "欧洲国家联赛",
        "欧洲杯",
        "欧洲杯预选赛",
        "瑞典杯",
        "美国公开赛杯",
        "美洲杯",
        "葡萄牙杯",
    }

    assert current_leagues == set(OFFICIAL_LEAGUE_REFS) | set(MANUAL_SEASON_CANDIDATES)


def test_emperors_cup_uses_full_2025_season_before_2026_start():
    selected = select_season_window(
        list(MANUAL_SEASON_CANDIDATES["日本天皇杯"]),
        today=date(2026, 7, 13),
    )

    assert selected.season_name == "2025"
    assert selected.start_date == date(2025, 5, 24)
    assert selected.end_date == date(2025, 11, 22)
    assert selected.selection_reason == "previous_complete"
