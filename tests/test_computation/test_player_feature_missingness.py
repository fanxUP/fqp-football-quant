"""Player facts must not manufacture numeric strength or absence evidence."""

from unittest.mock import MagicMock, patch

import pytest

from scripts.feature_storage import store_match_lineup_snapshot
from scripts.features.build_injury_impact import (
    build_injury_features,
    compute_absence_impact,
    compute_team_absence_impact,
)
from scripts.features.build_lineup_strength import (
    build_lineup_features,
    compute_lineup_strength,
    compute_rotation_risk,
)
from scripts.jobs import collect_injury_data, collect_lineup_data


def test_collected_lineup_preserves_roster_without_inventing_player_quality():
    source = dict(
        formation="4-3-3",
        startXI=[dict(player=dict(id=i, name=f"P{i}", pos="D")) for i in range(1, 12)],
        substitutes=[dict(player=dict(id=12, name="Sub", pos="F"))],
    )
    with (
        patch.object(collect_lineup_data, "_get_or_create_player", side_effect=range(101, 113)),
        patch.object(collect_lineup_data, "store_lineup_observation", return_value=501) as store,
    ):
        collect_lineup_data._process_lineup(
            MagicMock(), 7, source, 11, "2026-10-24T12:00:00", api_fixture_id=900
        )
    snapshot, players = store.call_args.args[1:]
    assert snapshot["lineup_type"] == "confirmed"
    assert snapshot["formation"] == "4-3-3"
    for field in (
        "formation_changed",
        "goalkeeper_changed",
        "center_back_pair_changed",
        "starting_11_key_player_count",
        "bench_strength_score",
        "lineup_strength_score",
        "rotation_risk_score",
        "lineup_uncertainty_score",
    ):
        assert snapshot[field] is None, field
    assert len(players) == 12
    assert all(player["key_player_score"] is None for player in players)


def test_collected_injury_preserves_report_without_inventing_impact():
    match = dict(id=7, home_team_id=11, away_team_id=12, competition_season_id=1)
    source = [
        dict(
            team=dict(name="Home"),
            player=dict(
                id=4, name="P4", position="Goalkeeper", type="Missing Fixture", reason="Knee Injury"
            ),
        )
    ]
    with (
        patch.object(collect_injury_data, "_get_or_create_player", return_value=104),
        patch.object(collect_injury_data, "store_injury_observations") as store,
    ):
        collect_injury_data._process_fixture_injuries(
            MagicMock(), match, 900, source, {"Home": 11, "Away": 12}, "2026-10-24T12:00:00"
        )
    player = store.call_args.kwargs["players"][0]
    assert player["injury_body_part"] == "Knee Injury"
    for field in (
        "recent_minutes_share",
        "team_market_value_share",
        "position_importance_score",
        "replacement_quality_score",
        "absence_impact_score",
    ):
        assert player[field] is None, field
    for summary in store.call_args.kwargs["summaries"]:
        assert summary["key_absence_count"] is None
        assert summary["squad_health_score"] is None


def complete_lineup():
    return dict(
        starting_11_market_value=0,
        recent_minutes_stability=0,
        key_player_integrity=0,
        positional_completeness=0,
        formation_stability=0,
        bench_strength_score=0,
    )


def test_lineup_known_zero_is_not_replaced_with_fifty():
    assert compute_lineup_strength(complete_lineup(), league_reference_value=100) == 0


def test_complete_lineup_components_keep_the_existing_weighted_rule():
    lineup = dict.fromkeys(complete_lineup(), 100)
    assert compute_lineup_strength(lineup, league_reference_value=100) == pytest.approx(92.5)


@pytest.mark.parametrize("field", list(complete_lineup()))
def test_partial_lineup_cannot_claim_a_complete_strength_score(field):
    lineup = complete_lineup()
    lineup[field] = None
    assert compute_lineup_strength(lineup, league_reference_value=100) is None


def test_lineup_without_a_reference_value_has_unknown_strength():
    assert compute_lineup_strength(complete_lineup()) is None


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -1, 101])
def test_invalid_lineup_component_remains_unknown(value):
    lineup = dict(complete_lineup(), bench_strength_score=value)
    assert compute_lineup_strength(lineup, league_reference_value=100) is None


def test_rotation_requires_evidence_for_every_change_and_preserves_false():
    assert compute_rotation_risk({}) is None
    lineup = dict(
        formation_changed=False,
        goalkeeper_changed=False,
        center_back_pair_changed=False,
        lineup_uncertainty_score=0,
    )
    assert compute_rotation_risk(lineup) == 0
    assert compute_rotation_risk(dict(lineup, goalkeeper_changed=True)) == 20
    assert compute_rotation_risk(dict(lineup, center_back_pair_changed=None)) is None


@pytest.mark.parametrize(
    "changes", [{}, {"goalkeeper_changed": False}, {"goalkeeper_changed": True}]
)
def test_lineup_storage_preserves_unknown_false_and_true(changes):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [None, (1,)]
    assert store_match_lineup_snapshot(conn, dict(match_id=7, team_id=11, **changes)) == 1
    params = cursor.execute.call_args.args[1]
    assert params["formation_changed"] is None
    assert params["goalkeeper_changed"] is changes.get("goalkeeper_changed")


def test_legacy_fixed_lineup_scores_do_not_become_new_feature_evidence():
    with patch(
        "scripts.features.build_lineup_strength.get_lineup_for_match",
        return_value=dict(lineup_type="confirmed", lineup_strength_score=50, rotation_risk_score=5),
    ):
        result = build_lineup_features(MagicMock(), 7, 11, 12)
    assert result["has_lineup_data"] is True
    for field in (
        "home_lineup_strength_score",
        "away_lineup_strength_score",
        "lineup_strength_diff",
        "home_rotation_risk_score",
        "away_rotation_risk_score",
        "rotation_risk_diff",
    ):
        assert result[field] is None


def complete_absence():
    return dict(
        availability_status="injured",
        recent_minutes_share=0,
        team_market_value_share=0,
        position_importance_score=0,
        key_player_score=0,
        replacement_difficulty=0,
    )


def test_known_zero_absence_components_remain_zero():
    assert compute_absence_impact(complete_absence()) == 0


def test_unknown_availability_cannot_produce_an_absence_score():
    assert compute_absence_impact(dict(complete_absence(), availability_status="unknown")) is None


def test_complete_absence_components_keep_the_existing_weighted_rule():
    player = dict(
        complete_absence(),
        recent_minutes_share=0.5,
        team_market_value_share=0.2,
        position_importance_score=0.8,
        key_player_score=60,
        replacement_difficulty=0.4,
    )
    assert compute_absence_impact(player) == pytest.approx(49)
    assert compute_team_absence_impact([player]) == {
        "total_impact_score": 49,
        "key_absence_count": 1,
    }


@pytest.mark.parametrize(
    "field", [key for key in complete_absence() if key != "availability_status"]
)
def test_partial_absence_components_do_not_produce_impact(field):
    player = complete_absence()
    player[field] = None
    assert compute_absence_impact(player) is None


def test_legacy_position_only_injury_score_is_not_reused_as_validated_impact():
    result = compute_team_absence_impact(
        [
            dict(
                availability_status="injured",
                absence_impact_score=80,
                position_importance_score=0.95,
            )
        ]
    )
    assert result["total_impact_score"] is None
    assert result["key_absence_count"] is None


def test_partial_team_impact_does_not_silently_skip_unscored_players():
    assert compute_team_absence_impact(
        [complete_absence(), dict(availability_status="injured")]
    ) == {
        "total_impact_score": None,
        "key_absence_count": None,
    }


def test_injury_read_failure_does_not_leave_a_fabricated_zero_score():
    with (
        patch(
            "scripts.features.build_injury_impact.get_injuries_for_match",
            side_effect=RuntimeError("fixed"),
        ),
        patch(
            "scripts.features.build_injury_impact.get_injury_observation_for_match", return_value={}
        ),
    ):
        result = build_injury_features(MagicMock(), 7, 11, 12)
    assert result["home_absence_impact_score"] is None
    assert result["away_absence_impact_score"] is None


def test_injury_source_coverage_does_not_imply_impact_coverage():
    with (
        patch(
            "scripts.features.build_injury_impact.get_injuries_for_match",
            return_value=[dict(availability_status="injured")],
        ),
        patch(
            "scripts.features.build_injury_impact.get_injury_observation_for_match",
            return_value={"injured_players_count": 1},
        ),
    ):
        result = build_injury_features(MagicMock(), 7, 11, 12)
    assert result["has_injury_data"] is True
    assert result["home_absence_impact_score"] is None
    assert result["away_absence_impact_score"] is None
    assert result["absence_impact_diff"] is None
