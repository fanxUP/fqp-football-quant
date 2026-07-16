from unittest.mock import MagicMock, patch

from scripts.features.build_injury_impact import build_injury_features
from scripts.features.build_lineup_strength import build_lineup_features
from scripts.features.build_motivation_score import build_motivation_features
from scripts.features.build_tournament_incentive import build_tournament_incentive_features


def test_injury_coverage_requires_actual_source_rows_not_only_team_ids():
    with patch(
        "scripts.features.build_injury_impact.get_injuries_for_team",
        side_effect=[[], []],
    ):
        result = build_injury_features(MagicMock(), 7, 11, 12)

    assert result["home_absence_impact_score"] is None
    assert result["away_absence_impact_score"] is None
    assert result["has_injury_data"] is False
    assert result["covered_team_count"] == 0


def test_lineup_coverage_is_partial_until_both_teams_have_rows():
    with patch(
        "scripts.features.build_lineup_strength.get_lineup_for_match",
        side_effect=[{"lineup_type": "confirmed"}, None],
    ):
        result = build_lineup_features(MagicMock(), 7, 11, 12)

    assert result["has_lineup_data"] is False
    assert result["covered_team_count"] == 1


def test_motivation_defaults_are_not_reported_as_source_backed_without_standings():
    with (
        patch(
            "scripts.features.build_motivation_score.get_latest_standings",
            return_value=[],
        ),
        patch("scripts.features.build_motivation_score.store_team_motivation_snapshot"),
    ):
        result = build_motivation_features(MagicMock(), 7, 11, 12, 99)

    assert result["home_motivation_score"] is None
    assert result["away_motivation_score"] is None
    assert result["has_motivation_data"] is False
    assert result["used_default_estimate"] is True


def test_tournament_defaults_are_not_emitted_without_motivation_evidence():
    with patch(
        "scripts.features.build_tournament_incentive.get_motivation_for_match",
        return_value=[],
    ):
        result = build_tournament_incentive_features(MagicMock(), 7, 11, 12)

    assert result["home_tanking_risk_score"] is None
    assert result["away_tanking_risk_score"] is None
    assert result["has_tournament_incentive_data"] is False
