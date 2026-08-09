-- Explicit opt-in for scheduled external model calls. Disabled by default.
CREATE TABLE IF NOT EXISTS report_automation_settings (
    setting_key VARCHAR(64) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

INSERT INTO report_automation_settings (setting_key, enabled)
VALUES ('post_match_report', false)
ON CONFLICT (setting_key) DO NOTHING;
