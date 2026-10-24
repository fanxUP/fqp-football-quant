import json
from datetime import date, datetime
from hashlib import sha256
from unittest.mock import MagicMock, patch

import pytest
from psycopg2.extras import Json

from scripts.mle_trainer import (
    _load_match_data,
    _load_training_dataset,
    fit_bivariate_poisson_shared,
    run,
)
from scripts.model_artifact_identity import (
    attach_artifact_identity,
    canonical_json_bytes,
    verify_artifact_identity,
)


def _artifact_source_tree(tmp_path):
    source_root = tmp_path / "repo"
    scripts_dir = source_root / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "mle_trainer.py").write_text("trainer-v1", encoding="utf-8")
    (scripts_dir / "training_manifest.py").write_text("manifest-v1", encoding="utf-8")
    return source_root


def _sample_training_manifest(
    selection_version="settled-official-score-team-history/v1",
):
    manifest = {
        "version": "fqp.maher-spf-training-manifest/v1",
        "selection_version": selection_version,
        "minimum_team_matches": 3,
        "cutoff_at": None,
        "training_start": None,
        "training_end": None,
        "included": [],
        "excluded": [],
    }
    return {
        **manifest,
        "sha256": sha256(canonical_json_bytes(manifest)).hexdigest(),
    }


def test_artifact_identity_is_stable_and_binds_parameters_and_manifest(tmp_path):
    source_root = _artifact_source_tree(tmp_path)
    first = {"attack": {20: -0.1, 10: 0.2}, "home_advantage": 0.2}
    reordered = {"home_advantage": 0.2, "attack": {10: 0.2, 20: -0.1}}

    artifact_a = attach_artifact_identity(
        first, _sample_training_manifest(), source_root=source_root
    )
    artifact_b = attach_artifact_identity(
        reordered, _sample_training_manifest(), source_root=source_root
    )
    changed_parameters = attach_artifact_identity(
        {"attack": {10: 0.3, 20: -0.1}, "home_advantage": 0.2},
        _sample_training_manifest(),
        source_root=source_root,
    )
    changed_manifest = attach_artifact_identity(
        first,
        _sample_training_manifest("changed-selection/v2"),
        source_root=source_root,
    )

    metadata = artifact_a["_artifact_identity"]
    assert artifact_a == artifact_b
    assert (
        metadata["sha256"]
        == sha256(
            canonical_json_bytes(
                {
                    "attack": {"10": 0.2, "20": -0.1},
                    "home_advantage": 0.2,
                }
            )
        ).hexdigest()
    )
    assert metadata["size_bytes"] == len(
        canonical_json_bytes({"attack": {"10": 0.2, "20": -0.1}, "home_advantage": 0.2})
    )
    assert metadata["training_manifest_sha256"] == _sample_training_manifest()["sha256"]
    assert metadata["source_files"] == {
        "scripts/mle_trainer.py": sha256(b"trainer-v1").hexdigest(),
        "scripts/training_manifest.py": sha256(b"manifest-v1").hexdigest(),
    }
    assert changed_parameters["_artifact_identity"]["sha256"] != metadata["sha256"]
    assert (
        changed_manifest["_artifact_identity"]["training_manifest_sha256"]
        != metadata["training_manifest_sha256"]
    )
    with pytest.raises(ValueError, match="manifest SHA-256"):
        attach_artifact_identity(
            first,
            {**_sample_training_manifest(), "included": [{"match_id": 1}]},
            source_root=source_root,
        )


def test_artifact_integrity_rejects_parameter_manifest_size_and_source_tampering(
    tmp_path,
):
    source_root = _artifact_source_tree(tmp_path)
    artifact = attach_artifact_identity(
        {"attack": {10: 0.2}, "home_advantage": 0.2},
        _sample_training_manifest(),
        source_root=source_root,
    )
    verify_artifact_identity(
        artifact,
        expected_manifest_sha256=_sample_training_manifest()["sha256"],
        source_root=source_root,
    )

    with pytest.raises(ValueError, match="parameter hash"):
        verify_artifact_identity({**artifact, "attack": {"10": 0.9}}, source_root=source_root)
    with pytest.raises(ValueError, match="manifest"):
        verify_artifact_identity(
            artifact,
            expected_manifest_sha256="b" * 64,
            source_root=source_root,
        )
    with pytest.raises(ValueError, match="size"):
        verify_artifact_identity(
            {
                **artifact,
                "_artifact_identity": {
                    **artifact["_artifact_identity"],
                    "size_bytes": artifact["_artifact_identity"]["size_bytes"] + 1,
                },
            },
            source_root=source_root,
        )

    (source_root / "scripts" / "mle_trainer.py").write_text("trainer-v2", encoding="utf-8")
    with pytest.raises(ValueError, match="source fingerprint"):
        verify_artifact_identity(artifact, source_root=source_root)


def test_artifact_identity_rejects_noncanonical_json_keys_and_nonfinite_values():
    with pytest.raises(ValueError, match="key collision"):
        canonical_json_bytes({1: "integer", "1": "string"})
    with pytest.raises(ValueError, match="finite"):
        canonical_json_bytes({"value": float("nan")})
    assert canonical_json_bytes({"value": -0.0}) == b'{"value":0.0}'


def test_bivariate_trainer_fits_a_safe_shared_component_from_settled_results() -> None:
    conn = MagicMock()
    maher = {
        "attack": {10: 0.2, 20: -0.1},
        "defense": {10: -0.1, 20: 0.2},
        "home_advantage": 0.2,
        "league_intercept": 0.1,
    }
    with patch(
        "scripts.mle_trainer._load_match_data",
        return_value=(
            [10, 20],
            {10: 0, 20: 1},
            [0, 1, 0],
            [1, 0, 1],
            [1, 0, 2],
            [1, 0, 1],
        ),
    ):
        result = fit_bivariate_poisson_shared(conn, maher)

    assert result["converged"] is True
    assert result["n_matches"] == 3
    assert 0 <= result["shared_goal_component"] < 0.3


def test_mle_run_adapts_parameter_dicts_for_jsonb_without_missing_updated_at_column():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    cur.fetchone.side_effect = [(41,), (42,), (43,)]
    db_context = MagicMock()
    db_context.__enter__.return_value = conn
    trained = {
        "maher_poisson": {
            "attack": {1: 0.1},
            "defense": {1: -0.1},
            "home_advantage": 0.2,
            "league_intercept": 0.4,
            "n_matches": 20,
            "n_teams": 2,
            "nll": 10.0,
            "converged": True,
            "training_manifest": _sample_training_manifest(),
        },
        "dixon_coles_rho": {"rho": -0.08, "nll": 5.0, "n_low_score_matches": 6},
        "bivariate_poisson": {
            "shared_goal_component": 0.1,
            "n_matches": 20,
            "converged": True,
            "nll": 10.0,
        },
    }

    with (
        patch("apps.backend.src.db.get_db", return_value=db_context),
        patch("scripts.mle_trainer.fit_all_models", return_value=trained),
    ):
        result = run()

    assert result["status"] == "ok"
    assert cur.execute.call_count == 6
    for call in cur.execute.call_args_list:
        query = call.args[0]
        assert "updated_at" not in query
    insert_calls = [
        call for call in cur.execute.call_args_list if "INSERT INTO model_versions" in call.args[0]
    ]
    assert all(isinstance(call.args[1][5], Json) for call in insert_calls)
    manifest_call = next(
        call
        for call in cur.execute.call_args_list
        if "INSERT INTO model_training_manifests" in call.args[0]
    )
    assert manifest_call.args[1][0] == 41
    assert manifest_call.args[1][1].adapted["sha256"] == _sample_training_manifest()["sha256"]
    conn.commit.assert_called_once()


def test_training_data_excludes_unmapped_teams_and_applies_minimum_history() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value
    cur.fetchall.return_value = [
        (1, 101, datetime(2026, 1, 1), None, 10, [10], 20, [20], 2, 1, "settled"),
        (2, 102, datetime(2026, 1, 2), None, 20, [20], 10, [10], 0, 0, "settled"),
        (3, 103, datetime(2026, 1, 3), None, None, [10, 11], 20, [20], 1, 0, "settled"),
    ]

    team_ids, _, home_idx, away_idx, home_goals, away_goals = _load_match_data(
        conn,
        min_matches=2,
    )

    query, params = cur.execute.call_args.args
    normalized = " ".join(query.split())
    assert "JOIN LATERAL" in normalized
    assert "WHERE candidate.team_name_cn = m.home_team_name" in normalized
    assert "WHERE candidate.team_name_cn = m.away_team_name" in normalized
    assert "array_agg(candidate.id ORDER BY candidate.id)" in normalized
    assert "CASE WHEN COUNT(candidate.id) = 1 THEN MIN(candidate.id) END" in normalized
    assert "ORDER BY candidate.id LIMIT 1" not in normalized
    assert "COALESCE(t1.id, 0)" not in normalized
    assert "LEFT JOIN official_results" in normalized
    assert params == ()
    assert team_ids == [10, 20]
    assert home_idx == [0, 1]
    assert away_idx == [1, 0]
    assert home_goals == [2, 0]
    assert away_goals == [1, 0]


def test_ambiguous_training_team_mapping_is_excluded_with_candidate_ids() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value
    cur.fetchall.return_value = [
        (
            1,
            1001,
            datetime(2026, 1, 1),
            datetime(2026, 1, 2),
            10,
            [10],
            20,
            [20],
            1,
            0,
            "settled",
        ),
        (
            2,
            1002,
            datetime(2026, 1, 2),
            datetime(2026, 1, 3),
            None,
            [10, 11],
            20,
            [20],
            2,
            1,
            "settled",
        ),
    ]

    dataset = _load_training_dataset(conn, min_matches=1)

    assert [sample.match_id for sample in dataset.samples] == [1]
    assert [(entry.match_id, entry.reason) for entry in dataset.manifest.excluded] == [
        (2, "team_identity_ambiguous:home=[10,11]")
    ]


def test_mle_run_rejects_non_converged_fit_without_changing_active_versions():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    db_context = MagicMock()
    db_context.__enter__.return_value = conn
    trained = {
        "maher_poisson": {
            "n_matches": 5286,
            "n_teams": 721,
            "nll": 100.0,
            "converged": False,
            "optimizer_message": "iteration limit reached",
        },
        "dixon_coles_rho": {"rho": -0.054, "nll": 50.0},
    }

    with (
        patch("apps.backend.src.db.get_db", return_value=db_context),
        patch("scripts.mle_trainer.fit_all_models", return_value=trained),
    ):
        result = run()

    assert result == {
        "status": "error",
        "error": "Maher MLE did not converge",
        "optimizer_message": "iteration limit reached",
    }
    cur.execute.assert_not_called()
    conn.commit.assert_not_called()


def test_mle_run_creates_new_active_versions_without_overwriting_history():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    cur.fetchone.side_effect = [(41,), (42,), (43,)]
    db_context = MagicMock()
    db_context.__enter__.return_value = conn
    trained = {
        "maher_poisson": {
            "attack": {1: 0.1},
            "defense": {1: -0.1},
            "home_advantage": 0.2,
            "league_intercept": 0.4,
            "n_matches": 20,
            "n_teams": 2,
            "nll": 10.0,
            "converged": True,
            "training_start_date": date(2025, 1, 1),
            "training_end_date": date(2026, 7, 21),
            "training_manifest": _sample_training_manifest(),
        },
        "dixon_coles_rho": {"rho": -0.08, "nll": 5.0, "n_low_score_matches": 6},
        "bivariate_poisson": {
            "shared_goal_component": 0.1,
            "n_matches": 20,
            "converged": True,
            "nll": 10.0,
        },
    }

    with (
        patch("apps.backend.src.db.get_db", return_value=db_context),
        patch("scripts.mle_trainer.fit_all_models", return_value=trained),
    ):
        result = run()

    assert result["status"] == "ok"
    queries = [" ".join(call.args[0].split()) for call in cur.execute.call_args_list]
    assert queries[0].startswith("UPDATE model_versions SET is_active = false")
    assert queries[1].startswith("UPDATE model_versions SET is_active = false")
    assert sum(query.startswith("INSERT INTO model_versions") for query in queries) == 3
    assert sum(query.startswith("INSERT INTO model_training_manifests") for query in queries) == 1
    assert queries.index(
        next(q for q in queries if q.startswith("INSERT INTO model_training_manifests"))
    ) > queries.index(next(q for q in queries if q.startswith("INSERT INTO model_versions")))
    model_insert_queries = [
        query for query in queries if query.startswith("INSERT INTO model_versions")
    ]
    assert all("training_start_date" in query for query in model_insert_queries)
    assert all("training_end_date" in query for query in model_insert_queries)
    assert all("is_active" in query for query in model_insert_queries)
    insert_params = [
        call.args[1]
        for call in cur.execute.call_args_list
        if "INSERT INTO model_versions" in call.args[0]
    ]
    assert {params[0] for params in insert_params} == {
        "maher_poisson",
        "dixon_coles",
        "bivariate_poisson",
    }
    assert len({params[2] for params in insert_params}) == 1
    assert all(params[3] == date(2025, 1, 1) for params in insert_params)
    assert all(params[4] == date(2026, 7, 21) for params in insert_params)
    for params in insert_params:
        json.dumps(params[5].adapted)

    maher_parameters = next(
        params[5].adapted for params in insert_params if params[0] == "maher_poisson"
    )
    assert "training_manifest" not in maher_parameters
    assert maher_parameters["attack"] == {"1": 0.1}
    assert (
        maher_parameters["_artifact_identity"]["training_manifest_sha256"]
        == (_sample_training_manifest()["sha256"])
    )
    assert maher_parameters["_artifact_identity"]["model_name"] == "maher_poisson"
    manifest_insert = next(
        call.args[1]
        for call in cur.execute.call_args_list
        if "INSERT INTO model_training_manifests" in call.args[0]
    )
    assert manifest_insert[0] == 41
    assert manifest_insert[1].adapted["sha256"] == _sample_training_manifest()["sha256"]
    assert result["model_version_ids"] == {
        "maher_poisson": 41,
        "dixon_coles": 42,
        "bivariate_poisson": 43,
    }


def test_mle_run_rolls_back_activation_when_manifest_persistence_fails():
    from contextlib import contextmanager

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = (41,)
    trained = {
        "maher_poisson": {
            "attack": {1: 0.1},
            "defense": {1: -0.1},
            "home_advantage": 0.2,
            "league_intercept": 0.4,
            "n_matches": 20,
            "n_teams": 2,
            "nll": 10.0,
            "converged": True,
            "training_manifest": _sample_training_manifest(),
        },
        "dixon_coles_rho": {"rho": -0.08, "nll": 5.0, "n_low_score_matches": 6},
    }

    @contextmanager
    def transactional_connection():
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise

    with (
        patch("apps.backend.src.db.get_db", return_value=transactional_connection()),
        patch("scripts.mle_trainer.fit_all_models", return_value=trained),
        patch(
            "scripts.model_training_manifest_storage.persist_training_manifest",
            side_effect=RuntimeError("manifest insert failed"),
        ),
        pytest.raises(RuntimeError, match="manifest insert failed"),
    ):
        run()

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_mle_run_rejects_missing_manifest_before_deactivating_active_version():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    db_context = MagicMock()
    db_context.__enter__.return_value = conn
    trained = {
        "maher_poisson": {
            "attack": {1: 0.1},
            "defense": {1: -0.1},
            "home_advantage": 0.2,
            "league_intercept": 0.4,
            "n_matches": 20,
            "n_teams": 2,
            "nll": 10.0,
            "converged": True,
        },
        "dixon_coles_rho": {"rho": -0.08, "nll": 5.0, "n_low_score_matches": 6},
    }

    with (
        patch("apps.backend.src.db.get_db", return_value=db_context),
        patch("scripts.mle_trainer.fit_all_models", return_value=trained),
    ):
        result = run()

    assert result["status"] == "error"
    assert "manifest" in result["error"].lower()
    cur.execute.assert_not_called()
    conn.commit.assert_not_called()
