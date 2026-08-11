from scripts.news_release_gate import apply_overlay_rows

ROW = (
    1,
    31,
    7,
    "spf",
    "3",
    0.45,
    0.4,
    0.08,
    0.8,
    0.2,
    11,
    5,
    "主队",
    "客队",
    "联赛",
    None,
    2.0,
    "dixon_coles",
)


def test_shadow_mode_never_changes_formal_prediction_rows() -> None:
    assert apply_overlay_rows([ROW], mode="shadow", overlays={(31, 7): {"3": 0.04}}) == [ROW]


def test_production_mode_changes_only_matching_spf_probability_and_ev() -> None:
    adjusted = apply_overlay_rows(
        [ROW],
        mode="production",
        overlays={(31, 7): {"3": 0.04, "1": -0.01, "0": -0.03}},
    )

    assert adjusted[0][5] == 0.49
    assert adjusted[0][7] == -0.02
    assert adjusted[0][0] == ROW[0]
