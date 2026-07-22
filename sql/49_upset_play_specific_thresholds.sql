-- Different market cardinalities require different cold-result thresholds.
UPDATE upset_rule_versions
SET is_active = false,
    valid_to = now()
WHERE is_active = true;

INSERT INTO upset_rule_versions (
    rule_key, description, thresholds_json, is_active, valid_from
) VALUES (
    'upset-v2',
    'Play-specific official closing probability thresholds',
    '{
        "S": 0.15,
        "A": 0.22,
        "B": 0.30,
        "C": 0.38,
        "favourite_min": 0.55,
        "by_play": {
            "zjq": {"S": 0.04, "A": 0.06, "B": 0.09, "C": 0.12},
            "bqc": {"S": 0.025, "A": 0.04, "B": 0.06, "C": 0.08},
            "bf": {"S": 0.005, "A": 0.01, "B": 0.02, "C": 0.03}
        }
    }',
    true,
    now()
);

