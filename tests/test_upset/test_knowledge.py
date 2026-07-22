from scripts.upset.knowledge import confidence_for_sample, decay_confidence


def test_knowledge_confidence_is_sample_bounded():
    assert confidence_for_sample(0) == 0.0
    assert confidence_for_sample(15) == 0.5
    assert confidence_for_sample(30) == 1.0
    assert confidence_for_sample(300) == 1.0


def test_old_knowledge_confidence_decays_by_half_life():
    assert decay_confidence(0.8, age_days=180, half_life_days=180) == 0.4
    assert decay_confidence(0.8, age_days=0, half_life_days=180) == 0.8
