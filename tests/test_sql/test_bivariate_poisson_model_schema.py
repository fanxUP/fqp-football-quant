from pathlib import Path


def test_bivariate_poisson_model_is_seeded_in_shadow_mode() -> None:
    source = Path("sql/74_add_bivariate_poisson_model.sql").read_text()

    assert "bivariate_poisson" in source
    assert '"rollout_mode":"shadow"' in source
    assert "ON CONFLICT (model_name, version) DO NOTHING" in source
