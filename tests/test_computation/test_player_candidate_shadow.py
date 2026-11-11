from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from scripts.player_candidate_shadow import build_player_candidate_shadow


def _ready_projection() -> dict:
    identity_revisions = [
        {
            "source_name": "api-football",
            "external_player_id": str(index),
            "player_id": index,
            "revision": 1,
            "updated_at": "2026-11-10T00:00:00+00:00",
        }
        for index in range(1, 23)
    ]
    identity_payload = json.dumps(
        identity_revisions, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return {
        "schema_version": "player-feature-projection/v1",
        "candidate": "player_dependent_shadow",
        "status": "candidate_inputs_ready",
        "match_id": 42,
        "feature_batch_id": 91,
        "observation_cutoff_id": str(uuid4()),
        "cutoff_as_of": "2026-11-11T04:59:00+00:00",
        "projected_at": "2026-11-11T05:00:00+00:00",
        "kickoff_at": "2026-11-11T08:00:00+00:00",
        "competition_season_id": 7,
        "identity_map_revision": {
            "entry_count": len(identity_revisions),
            "sha256": hashlib.sha256(identity_payload.encode("utf-8")).hexdigest(),
        },
        "coverage": {
            side: {
                "confirmed_lineup_players": 11,
                "identity_verified_players": 11,
                "registration_known": 11,
                "availability_report_complete": True,
            }
            for side in ("home", "away")
        },
        "feature_values": {
            "home_registered_starters": 11,
            "away_registered_starters": 11,
            "home_reported_unavailable_starters": 1,
            "away_reported_unavailable_starters": 0,
            "home_doubtful_starters": 0,
            "away_doubtful_starters": 1,
        },
        "missingness": [],
        "source_refs": {
            "lineup_revisions": {
                "home": {"revision_id": 101, "content_hash": "b" * 64},
                "away": {"revision_id": 102, "content_hash": "c" * 64},
            },
            "availability_revisions": {
                "home": {"revision_id": 201, "content_hash": "d" * 64},
                "away": {"revision_id": 202, "content_hash": "e" * 64},
            },
            "registration_fact_ids": list(range(301, 323)),
            "identity_mapping_revisions": identity_revisions,
        },
        "probabilities": None,
    }


def test_ready_player_projection_is_fingerprinted_but_candidate_withheld():
    candidate = build_player_candidate_shadow(_ready_projection())

    assert candidate["input_status"] == "ready"
    assert candidate["candidate_status"] == "withheld"
    assert candidate["reason"] == "player_effect_model_not_trained_or_evaluated"
    assert candidate["rollout_mode"] == "observation_only"
    assert candidate["probabilities"] is None
    assert candidate["applied_features"] == []
    assert candidate["missingness"] == []
    assert len(candidate["feature_projection_sha256"]) == 64


def test_player_candidate_hash_is_stable_and_binds_source_revisions():
    projection = _ready_projection()
    reordered = dict(reversed(list(projection.items())))
    changed = deepcopy(projection)
    changed["source_refs"]["lineup_revisions"]["home"]["content_hash"] = "f" * 64

    first = build_player_candidate_shadow(projection)
    second = build_player_candidate_shadow(reordered)
    third = build_player_candidate_shadow(changed)

    assert first["feature_projection_sha256"] == second["feature_projection_sha256"]
    assert first["feature_projection_sha256"] != third["feature_projection_sha256"]


def test_incomplete_projection_is_withheld_without_partial_feature_values():
    projection = _ready_projection()
    projection["status"] = "withheld"
    projection["feature_values"] = {}
    projection["missingness"] = ["registration_unknown", "identity_mapping_incomplete"]

    candidate = build_player_candidate_shadow(projection)

    assert candidate["input_status"] == "withheld"
    assert candidate["candidate_status"] == "withheld"
    assert candidate["reason"] == "player_inputs_incomplete"
    assert candidate["missingness"] == ["identity_mapping_incomplete", "registration_unknown"]
    assert candidate["probabilities"] is None


def test_malformed_withheld_projection_does_not_leak_untrusted_coverage():
    projection = _ready_projection()
    projection["status"] = "withheld"
    projection["feature_values"] = {}
    projection["missingness"] = ["registration_unknown"]
    projection["coverage"]["home"]["identity_verified_players"] = 12

    candidate = build_player_candidate_shadow(projection)

    assert candidate["reason"] == "player_projection_invalid"
    assert candidate["missingness"] == ["projection_invalid"]
    assert candidate["feature_projection_sha256"] is None


def test_ready_claim_with_post_kickoff_timestamp_is_withheld():
    projection = _ready_projection()
    projection["projected_at"] = "2026-11-11T08:00:00+00:00"

    candidate = build_player_candidate_shadow(projection)

    assert candidate["input_status"] == "withheld"
    assert candidate["reason"] == "player_projection_invalid"
    assert candidate["missingness"] == ["projection_invalid"]


def test_ready_claim_requires_registration_and_identity_evidence_to_match():
    missing_registration = _ready_projection()
    missing_registration["source_refs"]["registration_fact_ids"] = []
    future_identity = _ready_projection()
    future_identity["source_refs"]["identity_mapping_revisions"][0]["updated_at"] = (
        "2026-11-11T05:01:00+00:00"
    )
    identity_rows = future_identity["source_refs"]["identity_mapping_revisions"]
    identity_payload = json.dumps(
        identity_rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    future_identity["identity_map_revision"]["sha256"] = hashlib.sha256(
        identity_payload.encode("utf-8")
    ).hexdigest()

    missing = build_player_candidate_shadow(missing_registration)
    future = build_player_candidate_shadow(future_identity)

    assert missing["reason"] == "player_projection_invalid"
    assert future["reason"] == "player_projection_invalid"
    assert missing["candidate_status"] == future["candidate_status"] == "withheld"


def test_candidate_observation_does_not_change_base_maher_probability():
    from scripts.observed_maher_shadow import build_observed_maher_shadow

    cutoff_id = str(uuid4())
    batch = {
        "id": 91,
        "match_id": 42,
        "cutoff_id": cutoff_id,
        "builder_version": "observed-cutoff-pilot/v1",
        "features": {"temperature_2m": {"derivation": {"context": {}}}},
    }
    feature_input = {
        "status": "ready",
        "match_id": 42,
        "batch_id": 91,
        "cutoff_id": cutoff_id,
        "feature_columns": [
            "temperature_2m",
            "home_lineup_confirmed",
            "away_lineup_confirmed",
            "home_key_absence_count",
            "away_key_absence_count",
        ],
        "snapshot": {
            "feature_version": "observed-cutoff-pilot/v1",
            "feature_batch_id": 91,
            "observation_cutoff_id": cutoff_id,
            "home_team_id": 10,
            "away_team_id": 20,
            "temperature_2m": 12,
        },
        "field_statuses": {"temperature_2m": "value"},
    }
    model_parameters = {
        "maher_poisson": {
            "converged": True,
            "attack": {"10": 0.0, "20": 0.0},
            "defense": {"10": 0.0, "20": 0.0},
            "team_match_counts": {"10": 5, "20": 5},
            "n_matches": 10,
        }
    }
    common = dict(
        model_version_id=5,
        model_parameters=model_parameters,
        feature_input=feature_input,
        batch=batch,
        input_version=2,
        as_of=datetime(2026, 11, 11, 5, 0, tzinfo=UTC),
    )

    without_player = build_observed_maher_shadow(**common)
    with_player = build_observed_maher_shadow(**common, player_projection=_ready_projection())

    assert with_player["probabilities"] == without_player["probabilities"]
    assert (
        with_player["player_projection"]["feature_values"]["home_reported_unavailable_starters"]
        == 1
    )
    assert with_player["player_candidate"]["input_status"] == "ready"
    assert with_player["player_candidate"]["candidate_status"] == "withheld"
    assert with_player["player_candidate"]["probabilities"] is None
