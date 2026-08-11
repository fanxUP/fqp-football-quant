-- News Intelligence P5: explicit human promotion, version lock and rollback.
CREATE TABLE IF NOT EXISTS news_feature_release_settings (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    mode VARCHAR(16) NOT NULL DEFAULT 'shadow'
        CHECK (mode IN ('shadow', 'production')),
    approved_shadow_version VARCHAR(64),
    approved_feature_version VARCHAR(64),
    approval_note TEXT,
    approved_by VARCHAR(64),
    approved_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        mode = 'shadow'
        OR (approved_shadow_version IS NOT NULL AND approved_feature_version IS NOT NULL)
    )
);

INSERT INTO news_feature_release_settings (id, mode)
VALUES (1, 'shadow')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS news_feature_release_history (
    id BIGSERIAL PRIMARY KEY,
    action VARCHAR(16) NOT NULL CHECK (action IN ('promote', 'rollback')),
    previous_mode VARCHAR(16) NOT NULL,
    new_mode VARCHAR(16) NOT NULL,
    shadow_version VARCHAR(64),
    feature_version VARCHAR(64),
    sample_size INTEGER NOT NULL DEFAULT 0,
    brier_delta NUMERIC(12,9),
    log_loss_delta NUMERIC(12,9),
    action_note TEXT NOT NULL,
    actor VARCHAR(64) NOT NULL DEFAULT 'admin',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_feature_release_history_created
    ON news_feature_release_history (created_at DESC, id DESC);
