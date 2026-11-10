from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from scripts.dynamic_team_challenger import (
    _IMPLEMENTATION_SOURCE_PATHS,
    DynamicTeamConfig,
    DynamicTeamFixture,
    PromotionEvidence,
    SeasonMatchContext,
    _implementation_identity,
    _implementation_identity_sha256,
    fit_dynamic_team_challenger,
    predict_dynamic_team_challenger,
)
from scripts.model_artifact_identity import canonical_json_bytes
from scripts.training_manifest import CandidateMatch, build_training_dataset

FIT_CUTOFF = datetime(2026, 3, 1, 0, 0)
MEMBERSHIP_SHA = "a" * 64
VENUE_SHA = "b" * 64


def _dataset(*, season_id: int = 20262027, cutoff: datetime = FIT_CUTOFF):
    rows = []
    fixtures = ((1, 2), (3, 4), (1, 3), (2, 4), (1, 4), (2, 3))
    for index in range(18):
        kickoff = datetime(2026, 1, 1, 18) + timedelta(days=index * 2)
        home_team, away_team = fixtures[index % len(fixtures)]
        rows.append(
            CandidateMatch(
                match_id=1000 + index,
                result_id=2000 + index,
                kickoff_at=kickoff,
                home_team_id=home_team,
                away_team_id=away_team,
                home_goals=2 if home_team == 1 else index % 3,
                away_goals=0 if away_team == 2 else (index + 1) % 2,
                match_status="settled",
                official_publish_time=kickoff + timedelta(hours=3),
            )
        )
    dataset = build_training_dataset(rows, min_matches=1, cutoff_at=cutoff)
    contexts = {
        sample.match_id: SeasonMatchContext(
            competition_id=77,
            competition_season_id=season_id,
            neutral_venue=(sample.match_id % 5 == 0),
            season_membership_evidence_sha256=MEMBERSHIP_SHA,
            season_membership_available_at=FIT_CUTOFF - timedelta(days=1),
            venue_evidence_sha256=VENUE_SHA,
            venue_evidence_available_at=FIT_CUTOFF - timedelta(days=1),
        )
        for sample in dataset.samples
    }
    return dataset, contexts


def _resign_manifest(manifest: dict) -> dict:
    signed = dict(manifest)
    fields = (
        "version",
        "selection_version",
        "minimum_team_matches",
        "cutoff_at",
        "training_start",
        "training_end",
        "included",
        "excluded",
    )
    signed["sha256"] = hashlib.sha256(
        canonical_json_bytes({field: signed[field] for field in fields})
    ).hexdigest()
    return signed


def test_fit_binds_p106_manifest_season_context_and_decay_weights_deterministically():
    dataset, contexts = _dataset()

    first = fit_dynamic_team_challenger(dataset.manifest.to_dict(), contexts)
    second = fit_dynamic_team_challenger(
        dataset.manifest.to_dict(), dict(reversed(list(contexts.items())))
    )

    assert first.candidate_sha256 == second.candidate_sha256
    assert first.training_manifest_sha256 == dataset.manifest.sha256
    assert first.season_context_sha256 == second.season_context_sha256
    implementation = _implementation_identity()
    assert set(implementation["source_sha256_by_path"]) == set(_IMPLEMENTATION_SOURCE_PATHS)
    assert first.implementation_identity_sha256 == _implementation_identity_sha256()
    assert set(implementation["runtime"]) == {
        "python_implementation",
        "python_version",
        "numpy_version",
        "scipy_version",
    }
    assert first.competition_id == 77
    assert first.competition_season_id == 20262027
    oldest = min(first.training_sample_weights, key=lambda match_id: match_id)
    newest = max(first.training_sample_weights, key=lambda match_id: match_id)
    assert first.training_sample_weights[newest] > first.training_sample_weights[oldest]
    assert first.training_sample_weights[newest] / first.training_sample_weights[
        oldest
    ] == pytest.approx(2 ** (34 / first.config.half_life_days))
    assert first.config.model_version == "fqp.dynamic-team-poisson/v1"
    assert first.config.season_transition_policy == "neutral_reset_by_competition_season_id/v1"


def test_fit_rejects_a_manifest_whose_labels_were_not_available_at_its_cutoff():
    dataset, contexts = _dataset()
    manifest = dataset.manifest.to_dict()
    manifest["cutoff_at"] = "2026-01-01T20:00:00.000000"
    manifest = _resign_manifest(manifest)

    with pytest.raises(ValueError, match="published after the fit cutoff"):
        fit_dynamic_team_challenger(manifest, contexts)


def test_fit_rejects_missing_mixed_or_unverifiable_season_context():
    dataset, contexts = _dataset()
    one_missing = dict(contexts)
    one_missing.pop(next(iter(one_missing)))
    with pytest.raises(ValueError, match="exactly match manifest samples"):
        fit_dynamic_team_challenger(dataset.manifest.to_dict(), one_missing)

    mixed = dict(contexts)
    first_match = next(iter(mixed))
    mixed[first_match] = SeasonMatchContext(
        competition_id=77,
        competition_season_id=20252026,
        neutral_venue=False,
        season_membership_evidence_sha256=MEMBERSHIP_SHA,
        season_membership_available_at=FIT_CUTOFF - timedelta(days=1),
        venue_evidence_sha256=VENUE_SHA,
        venue_evidence_available_at=FIT_CUTOFF - timedelta(days=1),
    )
    with pytest.raises(ValueError, match="one canonical competition-season"):
        fit_dynamic_team_challenger(dataset.manifest.to_dict(), mixed)

    late_evidence = dict(contexts)
    first_match = next(iter(late_evidence))
    late_evidence[first_match] = replace(
        late_evidence[first_match],
        season_membership_available_at=FIT_CUTOFF + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="not available at the fit cutoff"):
        fit_dynamic_team_challenger(dataset.manifest.to_dict(), late_evidence)

    invalid_digest = dict(contexts)
    first_match = next(iter(invalid_digest))
    invalid_digest[first_match] = replace(
        invalid_digest[first_match], season_membership_evidence_sha256="not-a-digest"
    )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        fit_dynamic_team_challenger(dataset.manifest.to_dict(), invalid_digest)


def test_promoted_team_requires_evidence_and_receives_stronger_prior_shrinkage():
    dataset, contexts = _dataset()
    with pytest.raises(ValueError, match="promotion evidence reference"):
        fit_dynamic_team_challenger(
            dataset.manifest.to_dict(),
            contexts,
            promoted_team_evidence={4: PromotionEvidence("  ", FIT_CUTOFF)},
        )
    with pytest.raises(ValueError, match="not available at the fit cutoff"):
        fit_dynamic_team_challenger(
            dataset.manifest.to_dict(),
            contexts,
            promoted_team_evidence={
                4: PromotionEvidence("late-promotion-source", FIT_CUTOFF + timedelta(seconds=1))
            },
        )

    candidate = fit_dynamic_team_challenger(
        dataset.manifest.to_dict(),
        contexts,
        promoted_team_evidence={
            4: PromotionEvidence("official-season-membership:abc", FIT_CUTOFF - timedelta(days=1))
        },
    )
    assert candidate.team_prior_precision[4] == pytest.approx(
        candidate.config.team_prior_strength * candidate.config.promotion_prior_multiplier
    )
    assert candidate.promoted_team_evidence[4].evidence_ref == "official-season-membership:abc"


def test_prediction_applies_home_advantage_only_outside_neutral_venues_and_marks_new_teams():
    dataset, contexts = _dataset()
    model = fit_dynamic_team_challenger(dataset.manifest.to_dict(), contexts)
    kickoff = FIT_CUTOFF + timedelta(days=2)
    shared = dict(
        match_id=9001,
        competition_id=77,
        competition_season_id=20262027,
        home_team_id=999,
        away_team_id=998,
        kickoff_at=kickoff,
        prediction_as_of=FIT_CUTOFF + timedelta(days=1),
        venue_evidence_sha256=VENUE_SHA,
        venue_evidence_available_at=FIT_CUTOFF,
        season_membership_evidence_sha256=MEMBERSHIP_SHA,
        season_membership_available_at=FIT_CUTOFF,
    )

    home = predict_dynamic_team_challenger(model, DynamicTeamFixture(neutral_venue=False, **shared))
    neutral = predict_dynamic_team_challenger(
        model, DynamicTeamFixture(neutral_venue=True, **shared)
    )

    assert home["implementation_identity_sha256"] == model.implementation_identity_sha256
    assert neutral["implementation_identity_sha256"] == model.implementation_identity_sha256
    assert home["lambda_home"] / neutral["lambda_home"] == pytest.approx(
        math.exp(model.home_advantage_log)
    )
    assert home["lambda_away"] == pytest.approx(neutral["lambda_away"])
    assert home["home_advantage_applied"] is True
    assert neutral["home_advantage_applied"] is False
    assert home["home_team_coverage"] == "neutral_prior"
    assert home["away_team_coverage"] == "neutral_prior"
    assert model.base_home_goal_rate == pytest.approx(model.base_away_goal_rate)
    assert sum(home["spf_probabilities"].values()) == pytest.approx(1.0)
    assert all(0 <= value <= 1 for value in home["spf_probabilities"].values())

    late_membership = {
        **shared,
        "season_membership_available_at": FIT_CUTOFF + timedelta(days=2),
    }
    with pytest.raises(ValueError, match="not available at prediction_as_of"):
        predict_dynamic_team_challenger(
            model, DynamicTeamFixture(neutral_venue=False, **late_membership)
        )
    late_venue = {
        **shared,
        "venue_evidence_available_at": FIT_CUTOFF + timedelta(days=2),
    }
    with pytest.raises(ValueError, match="venue evidence was not available at prediction_as_of"):
        predict_dynamic_team_challenger(
            model, DynamicTeamFixture(neutral_venue=False, **late_venue)
        )


def test_all_neutral_and_all_home_training_do_not_double_count_home_advantage():
    dataset, contexts = _dataset()
    all_neutral = {
        match_id: replace(context, neutral_venue=True) for match_id, context in contexts.items()
    }
    neutral_model = fit_dynamic_team_challenger(dataset.manifest.to_dict(), all_neutral)
    assert neutral_model.home_advantage_training_matches == 0
    assert neutral_model.home_advantage_log == pytest.approx(
        neutral_model.config.home_advantage_prior_log
    )
    assert neutral_model.base_home_goal_rate == pytest.approx(neutral_model.base_away_goal_rate)

    all_home = {
        match_id: replace(context, neutral_venue=False) for match_id, context in contexts.items()
    }
    home_model = fit_dynamic_team_challenger(dataset.manifest.to_dict(), all_home)
    assert home_model.home_advantage_training_matches == len(dataset.samples)
    assert home_model.base_home_goal_rate == pytest.approx(home_model.base_away_goal_rate)
    kickoff = FIT_CUTOFF + timedelta(days=2)
    common = dict(
        match_id=9002,
        competition_id=77,
        competition_season_id=20262027,
        home_team_id=999,
        away_team_id=998,
        kickoff_at=kickoff,
        prediction_as_of=FIT_CUTOFF + timedelta(days=1),
        season_membership_evidence_sha256=MEMBERSHIP_SHA,
        season_membership_available_at=FIT_CUTOFF,
        venue_evidence_sha256=VENUE_SHA,
        venue_evidence_available_at=FIT_CUTOFF,
    )
    prediction = predict_dynamic_team_challenger(
        home_model, DynamicTeamFixture(neutral_venue=True, **common)
    )
    assert prediction["lambda_home"] == pytest.approx(prediction["lambda_away"])


def test_high_goal_rates_expand_the_score_grid_until_poisson_tail_is_negligible():
    dataset, contexts = _dataset()
    base_model = fit_dynamic_team_challenger(dataset.manifest.to_dict(), contexts)
    high_rate_model = replace(
        base_model,
        base_home_goal_rate=6.0,
        base_away_goal_rate=6.0,
        attack_log_rate={},
        defense_vulnerability_log_rate={},
        home_advantage_log=0.0,
        team_match_counts={},
    )
    fixture = DynamicTeamFixture(
        match_id=9003,
        competition_id=77,
        competition_season_id=20262027,
        home_team_id=999,
        away_team_id=998,
        kickoff_at=FIT_CUTOFF + timedelta(days=2),
        prediction_as_of=FIT_CUTOFF + timedelta(days=1),
        neutral_venue=True,
        season_membership_evidence_sha256=MEMBERSHIP_SHA,
        season_membership_available_at=FIT_CUTOFF,
        venue_evidence_sha256=VENUE_SHA,
        venue_evidence_available_at=FIT_CUTOFF,
    )
    prediction = predict_dynamic_team_challenger(high_rate_model, fixture)
    assert prediction["lambda_home"] == 6.0
    assert prediction["lambda_away"] == 6.0
    assert prediction["score_matrix_max_goals_used"] > 8
    assert prediction["omitted_score_tail_mass"] <= 1e-10
    assert (
        f"{prediction['score_matrix_max_goals_used']}:{prediction['score_matrix_max_goals_used']}"
        in prediction["score_matrix"]
    )
    assert sum(prediction["spf_probabilities"].values()) == pytest.approx(1.0)


def test_prediction_rejects_cross_season_and_temporal_leakage():
    dataset, contexts = _dataset()
    model = fit_dynamic_team_challenger(dataset.manifest.to_dict(), contexts)
    fixture = DynamicTeamFixture(
        match_id=9100,
        competition_id=77,
        competition_season_id=20252026,
        home_team_id=1,
        away_team_id=2,
        kickoff_at=FIT_CUTOFF + timedelta(days=2),
        prediction_as_of=FIT_CUTOFF + timedelta(days=1),
        neutral_venue=False,
        season_membership_evidence_sha256=MEMBERSHIP_SHA,
        season_membership_available_at=FIT_CUTOFF,
        venue_evidence_sha256=VENUE_SHA,
        venue_evidence_available_at=FIT_CUTOFF,
    )
    with pytest.raises(ValueError, match="does not match fitted competition-season"):
        predict_dynamic_team_challenger(model, fixture)

    too_early = DynamicTeamFixture(
        **{
            **fixture.__dict__,
            "competition_season_id": 20262027,
            "prediction_as_of": FIT_CUTOFF - timedelta(microseconds=1),
        }
    )
    with pytest.raises(ValueError, match="before the model cutoff"):
        predict_dynamic_team_challenger(model, too_early)

    after_kickoff = DynamicTeamFixture(
        **{
            **fixture.__dict__,
            "competition_season_id": 20262027,
            "prediction_as_of": FIT_CUTOFF + timedelta(days=3),
        }
    )
    with pytest.raises(ValueError, match="must be strictly before kickoff"):
        predict_dynamic_team_challenger(model, after_kickoff)


def test_config_rejects_invalid_decay_and_goal_rates():
    with pytest.raises(ValueError, match="half_life_days"):
        DynamicTeamConfig(half_life_days=0)
    with pytest.raises(ValueError, match="base_home_goal_rate_prior"):
        DynamicTeamConfig(base_home_goal_rate_prior=float("nan"))
