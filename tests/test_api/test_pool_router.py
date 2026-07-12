"""Pool router performance and contract tests."""

from apps.backend.src.routers import pool


def test_deterministic_pool_sample_is_computed_once(monkeypatch):
    calls = 0
    simulation_counts = []

    def fake_analyze(*args, **kwargs):
        nonlocal calls
        calls += 1
        simulation_counts.append(kwargs["n_mc_simulations"])
        return {"sample": True}

    monkeypatch.setattr(pool, "analyze_pool", fake_analyze)
    monkeypatch.setattr(pool, "pool_analysis_to_dict", lambda analysis: analysis)
    pool._build_pool_sample.cache_clear()

    assert pool.get_pool_sample() == {"sample": True}
    assert pool.get_pool_sample() == {"sample": True}
    assert calls == 1
    assert simulation_counts == [1_000]
