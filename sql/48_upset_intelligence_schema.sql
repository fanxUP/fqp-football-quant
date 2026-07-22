-- Cold-result research, evidence, reports, temporal knowledge and feature promotion.

CREATE TABLE IF NOT EXISTS upset_rule_versions (
    id BIGSERIAL PRIMARY KEY,
    rule_key VARCHAR(64) NOT NULL UNIQUE,
    description TEXT,
    thresholds_json JSONB NOT NULL,
    supported_play_types JSONB NOT NULL DEFAULT '["spf", "rqspf", "bf", "zjq", "bqc"]',
    is_active BOOLEAN NOT NULL DEFAULT false,
    valid_from TIMESTAMP NOT NULL DEFAULT now(),
    valid_to TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_upset_rule_one_active
    ON upset_rule_versions (is_active)
    WHERE is_active = true;

INSERT INTO upset_rule_versions (
    rule_key, description, thresholds_json, is_active
) VALUES (
    'upset-v1',
    'Official closing probability thresholds for objective cold-result research',
    '{"S": 0.15, "A": 0.22, "B": 0.30, "C": 0.38, "favourite_min": 0.55}',
    true
) ON CONFLICT (rule_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS upset_events (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES official_matches(id) ON DELETE CASCADE,
    business_date DATE NOT NULL,
    detect_rule_version_id BIGINT NOT NULL REFERENCES upset_rule_versions(id),
    official_result_id BIGINT NOT NULL REFERENCES official_results(id),
    primary_play_type VARCHAR(32) NOT NULL,
    primary_upset_type VARCHAR(64) NOT NULL,
    actual_outcome VARCHAR(64) NOT NULL,
    market_favourite_outcome VARCHAR(64),
    market_favourite_probability NUMERIC(10,6),
    actual_outcome_probability NUMERIC(10,6) NOT NULL
        CHECK (actual_outcome_probability > 0 AND actual_outcome_probability <= 1),
    surprise_bits NUMERIC(12,6) NOT NULL CHECK (surprise_bits >= 0),
    upset_level VARCHAR(8),
    favourite_failed BOOLEAN NOT NULL DEFAULT false,
    model_warned BOOLEAN,
    user_bet_involved BOOLEAN NOT NULL DEFAULT false,
    agent_bet_involved BOOLEAN NOT NULL DEFAULT false,
    detection_status VARCHAR(32) NOT NULL DEFAULT 'detected',
    detected_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (match_id, detect_rule_version_id)
);

CREATE INDEX IF NOT EXISTS idx_upset_events_date_level
    ON upset_events (business_date DESC, upset_level, id DESC);

CREATE TABLE IF NOT EXISTS upset_market_signals (
    id BIGSERIAL PRIMARY KEY,
    upset_event_id BIGINT NOT NULL REFERENCES upset_events(id) ON DELETE CASCADE,
    match_id BIGINT NOT NULL REFERENCES official_matches(id) ON DELETE CASCADE,
    play_type VARCHAR(32) NOT NULL,
    handicap NUMERIC(5,2),
    opening_snapshot_time TIMESTAMP,
    closing_snapshot_time TIMESTAMP NOT NULL,
    opening_odds_json JSONB,
    closing_odds_json JSONB NOT NULL,
    market_probabilities_json JSONB NOT NULL,
    market_overround NUMERIC(10,6),
    actual_outcome VARCHAR(64) NOT NULL,
    actual_outcome_probability NUMERIC(10,6) NOT NULL
        CHECK (actual_outcome_probability > 0 AND actual_outcome_probability <= 1),
    market_favourite_outcome VARCHAR(64),
    market_favourite_probability NUMERIC(10,6),
    odds_change_rate NUMERIC(12,6),
    surprise_bits NUMERIC(12,6) NOT NULL,
    upset_level VARCHAR(8),
    favourite_failed BOOLEAN NOT NULL DEFAULT false,
    detection_reasons_json JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_upset_market_signal_unique
    ON upset_market_signals (
        upset_event_id,
        play_type,
        COALESCE(handicap, 9999)
    );

CREATE TABLE IF NOT EXISTS upset_factor_evidence (
    id BIGSERIAL PRIMARY KEY,
    upset_event_id BIGINT NOT NULL REFERENCES upset_events(id) ON DELETE CASCADE,
    factor_category VARCHAR(64) NOT NULL,
    factor_code VARCHAR(128) NOT NULL,
    factor_value_json JSONB,
    factor_direction VARCHAR(32),
    evidence_phase VARCHAR(32) NOT NULL,
    available_before_kickoff BOOLEAN NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    source_reference TEXT,
    published_at TIMESTAMP,
    observed_at TIMESTAMP NOT NULL,
    available_at TIMESTAMP NOT NULL,
    confidence NUMERIC(10,6) CHECK (confidence >= 0 AND confidence <= 1),
    verification_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    raw_payload_hash VARCHAR(128),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (
        upset_event_id,
        factor_code,
        source_type,
        available_at,
        raw_payload_hash
    )
);

CREATE INDEX IF NOT EXISTS idx_upset_evidence_event_phase
    ON upset_factor_evidence (upset_event_id, evidence_phase, verification_status);

CREATE TABLE IF NOT EXISTS upset_reviews (
    id BIGSERIAL PRIMARY KEY,
    upset_event_id BIGINT NOT NULL REFERENCES upset_events(id) ON DELETE CASCADE,
    review_version VARCHAR(64) NOT NULL,
    prompt_version VARCHAR(64),
    model_name VARCHAR(128),
    summary TEXT,
    facts_json JSONB NOT NULL DEFAULT '[]',
    prematch_signals_json JSONB NOT NULL DEFAULT '[]',
    in_match_turning_points_json JSONB NOT NULL DEFAULT '[]',
    inferences_json JSONB NOT NULL DEFAULT '[]',
    hypotheses_json JSONB NOT NULL DEFAULT '[]',
    randomness_json JSONB NOT NULL DEFAULT '[]',
    model_postmortem_json JSONB NOT NULL DEFAULT '{}',
    actionable_lessons_json JSONB NOT NULL DEFAULT '[]',
    data_completeness NUMERIC(10,6) CHECK (data_completeness >= 0 AND data_completeness <= 1),
    confidence NUMERIC(10,6) CHECK (confidence >= 0 AND confidence <= 1),
    validation_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    validation_errors_json JSONB NOT NULL DEFAULT '[]',
    generated_at TIMESTAMP,
    published_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (upset_event_id, review_version)
);

CREATE TABLE IF NOT EXISTS upset_report_metrics (
    id BIGSERIAL PRIMARY KEY,
    report_type VARCHAR(32) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    data_cutoff_at TIMESTAMP NOT NULL,
    detect_rule_version_id BIGINT REFERENCES upset_rule_versions(id),
    report_version VARCHAR(64) NOT NULL,
    prompt_version VARCHAR(64),
    model_versions_json JSONB NOT NULL DEFAULT '[]',
    metrics_json JSONB NOT NULL,
    report_markdown TEXT,
    report_html TEXT,
    report_pdf_path TEXT,
    validation_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    generated_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (report_type, period_start, period_end, report_version)
);

CREATE TABLE IF NOT EXISTS league_knowledge_profiles (
    id BIGSERIAL PRIMARY KEY,
    competition_id BIGINT REFERENCES competitions(id),
    league_name VARCHAR(128) NOT NULL,
    season_id BIGINT REFERENCES seasons(id),
    valid_from DATE NOT NULL,
    valid_to DATE,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    sample_size INT NOT NULL CHECK (sample_size >= 0),
    metrics_json JSONB NOT NULL,
    summary_json JSONB NOT NULL DEFAULT '{}',
    source_snapshot_ids_json JSONB NOT NULL DEFAULT '[]',
    confidence NUMERIC(10,6) CHECK (confidence >= 0 AND confidence <= 1),
    knowledge_version VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (league_name, season_id, window_start, window_end, knowledge_version)
);

CREATE TABLE IF NOT EXISTS team_knowledge_profiles (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id),
    competition_id BIGINT REFERENCES competitions(id),
    season_id BIGINT REFERENCES seasons(id),
    coach_name VARCHAR(128),
    valid_from DATE NOT NULL,
    valid_to DATE,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    sample_size INT NOT NULL CHECK (sample_size >= 0),
    metrics_json JSONB NOT NULL,
    summary_json JSONB NOT NULL DEFAULT '{}',
    source_snapshot_ids_json JSONB NOT NULL DEFAULT '[]',
    confidence NUMERIC(10,6) CHECK (confidence >= 0 AND confidence <= 1),
    knowledge_version VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (team_id, competition_id, season_id, valid_from, knowledge_version)
);

CREATE TABLE IF NOT EXISTS player_knowledge_profiles (
    id BIGSERIAL PRIMARY KEY,
    player_id BIGINT NOT NULL REFERENCES players(id),
    team_id BIGINT NOT NULL REFERENCES teams(id),
    season_id BIGINT REFERENCES seasons(id),
    valid_from DATE NOT NULL,
    valid_to DATE,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    tactical_role VARCHAR(64),
    sample_size INT NOT NULL CHECK (sample_size >= 0),
    metrics_json JSONB NOT NULL,
    summary_json JSONB NOT NULL DEFAULT '{}',
    source_snapshot_ids_json JSONB NOT NULL DEFAULT '[]',
    confidence NUMERIC(10,6) CHECK (confidence >= 0 AND confidence <= 1),
    knowledge_version VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (player_id, team_id, season_id, valid_from, knowledge_version)
);

CREATE TABLE IF NOT EXISTS research_hypotheses (
    id BIGSERIAL PRIMARY KEY,
    hypothesis_key VARCHAR(128) NOT NULL,
    hypothesis_version VARCHAR(64) NOT NULL,
    source_upset_event_id BIGINT REFERENCES upset_events(id),
    title TEXT NOT NULL,
    description TEXT,
    conditions_json JSONB NOT NULL,
    target_json JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'research_only'
        CHECK (status IN (
            'research_only', 'backtesting', 'out_of_sample', 'simulation',
            'feature_candidate', 'promoted', 'rejected', 'retired'
        )),
    sample_size INT NOT NULL DEFAULT 0,
    confidence NUMERIC(10,6) CHECK (confidence >= 0 AND confidence <= 1),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (hypothesis_key, hypothesis_version)
);

CREATE TABLE IF NOT EXISTS hypothesis_validation_runs (
    id BIGSERIAL PRIMARY KEY,
    hypothesis_id BIGINT NOT NULL REFERENCES research_hypotheses(id) ON DELETE CASCADE,
    validation_type VARCHAR(32) NOT NULL,
    backtest_run_id BIGINT REFERENCES backtest_runs(id),
    train_start_date DATE,
    train_end_date DATE,
    test_start_date DATE,
    test_end_date DATE,
    metrics_json JSONB NOT NULL DEFAULT '{}',
    passed BOOLEAN,
    failure_reasons_json JSONB NOT NULL DEFAULT '[]',
    code_version VARCHAR(64),
    started_at TIMESTAMP NOT NULL DEFAULT now(),
    finished_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feature_promotion_audits (
    id BIGSERIAL PRIMARY KEY,
    hypothesis_id BIGINT NOT NULL REFERENCES research_hypotheses(id),
    from_status VARCHAR(32) NOT NULL,
    to_status VARCHAR(32) NOT NULL,
    feature_set_version VARCHAR(64),
    validation_run_ids_json JSONB NOT NULL DEFAULT '[]',
    decision_reason TEXT NOT NULL,
    decided_by VARCHAR(64) NOT NULL DEFAULT 'system_validation',
    rollback_reference TEXT,
    decided_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hypothesis_validation_hypothesis
    ON hypothesis_validation_runs (hypothesis_id, validation_type, started_at DESC);
