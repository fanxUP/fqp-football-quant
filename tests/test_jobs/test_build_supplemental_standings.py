from scripts.jobs.build_supplemental_standings import calculate


def test_calculate_ranks_points_and_goal_difference():
    rows = [(1, 2, 2, 0), (2, 3, 1, 1), (3, 1, 0, 1)]
    result = calculate(rows)
    assert [(row["team_id"], row["points"], row["rank"]) for row in result] == [
        (1, 6, 1), (3, 1, 2), (2, 1, 3)
    ]
