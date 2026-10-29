-- Sparse, append-only verification of existing odds rows. Raw publication is unchanged.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE football_history_odds_time_evidence (
    batch_id BIGINT NOT NULL,
    domain TEXT NOT NULL DEFAULT 'odds_history' CHECK (domain='odds_history'),
    source_record_key TEXT NOT NULL,
    source_match_id BIGINT NOT NULL,
    expected_value JSONB NOT NULL CHECK (jsonb_typeof(expected_value)='object'
        AND expected_value ?& ARRAY['company_id','odds_type','source','seq','change_time','home','line','away']),
    change_at TIMESTAMPTZ NOT NULL CHECK (isfinite(change_at)),
    time_basis TEXT NOT NULL CHECK (time_basis IN ('source_full','inferred_year')),
    effective_kickoff_at TIMESTAMPTZ NOT NULL CHECK (isfinite(effective_kickoff_at)),
    kickoff_basis TEXT NOT NULL CHECK (kickoff_basis IN ('source_schedule','source_and_official')),
    source_url TEXT NOT NULL,
    response_sha256 TEXT NOT NULL CHECK (response_sha256 ~ '^[0-9a-f]{64}$'),
    observed_at TIMESTAMPTZ NOT NULL,
    provenance JSONB NOT NULL CHECK (jsonb_typeof(provenance)='object'),
    imported_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (batch_id,source_record_key),
    FOREIGN KEY (batch_id,domain,source_record_key)
        REFERENCES football_history_records(batch_id,domain,source_record_key),
    FOREIGN KEY (batch_id,source_match_id)
        REFERENCES football_history_matches(batch_id,source_match_id)
);
CREATE INDEX idx_history_odds_evidence_match
    ON football_history_odds_time_evidence(batch_id,source_match_id);

CREATE FUNCTION protect_football_history_odds_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE m football_history_matches%ROWTYPE;
BEGIN
    IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Time evidence is immutable'; END IF;
    -- Serialize evidence for the same match without updating published source rows.
    SELECT * INTO m FROM football_history_matches
        WHERE batch_id=NEW.batch_id AND source_match_id=NEW.source_match_id FOR UPDATE;
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1 FROM football_history_records r JOIN football_history_batches b ON b.id=r.batch_id
        WHERE r.batch_id=NEW.batch_id AND r.domain='odds_history'
        AND r.source_record_key=NEW.source_record_key AND r.source_match_id=NEW.source_match_id
        AND b.state='published' AND b.source_name='titan007' AND r.value_json @> NEW.expected_value
    ) THEN RAISE EXCEPTION 'Evidence does not match published source content'; END IF;
    IF NEW.source_url<>format('https://1x2d.titan007.com/%s.js',NEW.source_match_id)
       OR NEW.provenance->>'home_team_id' IS DISTINCT FROM m.source_home_team_id::TEXT
       OR NEW.provenance->>'away_team_id' IS DISTINCT FROM m.source_away_team_id::TEXT
       OR NEW.expected_value->>'change_time' IS DISTINCT FROM
           to_char(NEW.change_at AT TIME ZONE 'Asia/Shanghai','MM-DD HH24:MI') THEN
        RAISE EXCEPTION 'Evidence identity or calendar does not match';
    END IF;
    IF NEW.effective_kickoff_at<>m.kickoff_at AND
       (NEW.kickoff_basis<>'source_and_official' OR
        coalesce(NEW.provenance->>'official_url','') NOT LIKE 'https://%') THEN
        RAISE EXCEPTION 'Changed kickoff requires official corroboration';
    END IF;
    IF EXISTS (SELECT 1 FROM football_history_odds_time_evidence
        WHERE batch_id=NEW.batch_id AND source_match_id=NEW.source_match_id
        AND effective_kickoff_at<>NEW.effective_kickoff_at) THEN
        RAISE EXCEPTION 'Conflicting reference kickoffs';
    END IF;
    IF NEW.time_basis='source_full' AND NEW.provenance->>'source_year' IS DISTINCT FROM
       extract(year FROM NEW.change_at AT TIME ZONE 'Asia/Shanghai')::INTEGER::TEXT THEN
        RAISE EXCEPTION 'Explicit source year is required';
    END IF;
    IF NEW.time_basis='inferred_year' AND (
        NOT NEW.provenance ?& ARRAY['event_start','anchor_at','event_url']
        OR coalesce(NEW.provenance->>'event_start','')=''
        OR coalesce(NEW.provenance->>'anchor_at','')=''
        OR coalesce(NEW.provenance->>'event_url','') NOT LIKE 'https://%'
        OR NEW.change_at<(NEW.provenance->>'event_start')::TIMESTAMPTZ
        OR NEW.change_at>(NEW.provenance->>'anchor_at')::TIMESTAMPTZ
        OR (NEW.provenance->>'anchor_at')::TIMESTAMPTZ NOT BETWEEN
            NEW.effective_kickoff_at-INTERVAL '4320 hours' AND NEW.effective_kickoff_at+INTERVAL '12 hours'
    ) THEN RAISE EXCEPTION 'Event inference requires a bounded event and existing-window anchor'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER protect_history_odds_evidence BEFORE INSERT OR UPDATE OR DELETE
    ON football_history_odds_time_evidence FOR EACH ROW
    EXECUTE FUNCTION protect_football_history_odds_evidence();
CREATE TRIGGER protect_history_odds_evidence_truncate BEFORE TRUNCATE
    ON football_history_odds_time_evidence EXECUTE FUNCTION reject_football_history_truncate();
GRANT SELECT ON football_history_odds_time_evidence TO fqp;

CREATE OR REPLACE FUNCTION football_history_odds_time_candidate(raw_time TEXT, kickoff TIMESTAMPTZ)
RETURNS TABLE(candidate_at TIMESTAMPTZ, candidate_basis TEXT, candidate_reason TEXT)
LANGUAGE plpgsql IMMUTABLE PARALLEL UNSAFE ROWS 1 AS $$
DECLARE
    value TEXT := btrim(raw_time);
    site_kickoff TIMESTAMP := kickoff AT TIME ZONE 'Asia/Shanghai';
    parts TEXT[];
    yr INTEGER;
    possible TIMESTAMPTZ;
    found_count INTEGER := 0;
    valid_calendar BOOLEAN := FALSE;
BEGIN
    candidate_basis := 'unresolved';
    IF value IS NULL OR value='' THEN
        candidate_reason := 'missing_time';
    ELSIF kickoff IS NULL OR NOT isfinite(kickoff) THEN
        candidate_reason := 'missing_kickoff';
    ELSIF value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T]([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?(Z|[+-][0-9]{2}:[0-9]{2})?$' THEN
        BEGIN
            IF value ~ '(Z|[+-][0-9]{2}:[0-9]{2})$' THEN
                possible := value::TIMESTAMPTZ;
            ELSE
                possible := value::TIMESTAMP AT TIME ZONE 'Asia/Shanghai';
            END IF;
            -- Hours, rather than calendar-day intervals, avoid session DST effects.
            candidate_at := possible;
            candidate_basis := 'source_full';
            candidate_reason := 'source_full_time';
        EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format OR invalid_parameter_value THEN
            candidate_reason := 'invalid_calendar_date';
        END;
    ELSE
        parts := regexp_match(value, '^([0-9]{2})-([0-9]{2}) ((?:[01][0-9]|2[0-3])):([0-5][0-9])$');
        IF parts IS NULL THEN
            candidate_reason := 'invalid_format';
        ELSE
            FOR yr IN extract(year FROM site_kickoff)::INTEGER-1 .. extract(year FROM site_kickoff)::INTEGER+1 LOOP
                BEGIN
                    possible := make_timestamp(yr,parts[1]::INTEGER,parts[2]::INTEGER,
                        parts[3]::INTEGER,parts[4]::INTEGER,0) AT TIME ZONE 'Asia/Shanghai';
                    valid_calendar := TRUE;
                    IF possible BETWEEN kickoff-INTERVAL '4320 hours' AND kickoff+INTERVAL '12 hours' THEN
                        candidate_at := possible;
                        found_count := found_count+1;
                    END IF;
                EXCEPTION WHEN datetime_field_overflow OR invalid_parameter_value THEN
                    NULL; -- February 29 must be checked in each candidate year.
                END;
            END LOOP;
            IF found_count=1 THEN
                candidate_basis := 'inferred_year';
                candidate_reason := 'unique_match_window';
            ELSE
                candidate_at := NULL;
                candidate_reason := CASE WHEN found_count>1 THEN 'ambiguous_year'
                    WHEN NOT valid_calendar THEN 'invalid_calendar_date'
                    ELSE 'outside_match_window' END;
            END IF;
        END IF;
    END IF;
    RETURN NEXT;
END $$;

CREATE OR REPLACE VIEW football_history_odds_timeline AS
WITH corrected_schedule AS (
    SELECT batch_id,source_match_id,min(effective_kickoff_at) AS effective_kickoff_at
    FROM football_history_odds_time_evidence WHERE kickoff_basis='source_and_official'
    GROUP BY batch_id,source_match_id
), candidates AS (
    SELECT h.*,
        coalesce(e.change_at,p.candidate_at) AS candidate_at,
        coalesce(e.time_basis,p.candidate_basis) AS candidate_basis,
        CASE WHEN e.time_basis='source_full' THEN 'source_year_evidence'
             WHEN e.time_basis='inferred_year' THEN 'event_sequence_evidence'
             ELSE p.candidate_reason END AS candidate_reason,
        coalesce(s.effective_kickoff_at,h.kickoff_at) AS effective_kickoff_at,
        CASE WHEN s.effective_kickoff_at IS NOT NULL THEN 'source_and_official'
             ELSE 'original_source_schedule' END AS kickoff_time_basis,
        e.source_url AS time_evidence_url,
        h.value_json->>'company_id' AS company_key,
        h.value_json->>'odds_type' AS market_key,
        h.value_json->>'source' AS feed_key,
        CASE WHEN h.value_json->>'seq' ~ '^[1-9][0-9]{0,8}$'
            THEN (h.value_json->>'seq')::BIGINT END AS seq
    FROM football_history_available h
    LEFT JOIN football_history_odds_time_evidence e
        ON e.batch_id=h.batch_id AND e.source_record_key=h.source_record_key
    LEFT JOIN corrected_schedule s ON s.batch_id=h.batch_id AND s.source_match_id=h.source_match_id
    CROSS JOIN LATERAL football_history_odds_time_candidate(h.value_json->>'change_time',
        coalesce(s.effective_kickoff_at,h.kickoff_at)) p
    WHERE h.domain='odds_history' AND h.source_name='titan007'
), ordered AS (
    SELECT c.*,
        min(candidate_at) OVER previous AS previous_min,
        max(candidate_at) OVER previous AS previous_max,
        lag(seq) OVER previous AS previous_seq
    FROM candidates c
    WINDOW previous AS (PARTITION BY batch_id,source_match_id,company_key,market_key,feed_key
        ORDER BY seq ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
), checked AS (
    SELECT o.*,
        coalesce(bool_or(candidate_at>previous_min) OVER grp,FALSE) AS has_increase,
        coalesce(bool_or(candidate_at<previous_max) OVER grp,FALSE) AS has_decrease,
        coalesce(bool_or(seq IS NULL OR seq=previous_seq OR company_key IS NULL
            OR company_key !~ '^[1-9][0-9]{0,17}$'
            OR market_key IS NULL OR market_key NOT IN ('europe','asian','overunder')
            OR feed_key IS NULL OR btrim(feed_key)='') OVER grp,FALSE) AS invalid_sequence
    FROM ordered o
    WINDOW grp AS (PARTITION BY batch_id,source_match_id,company_key,market_key,feed_key)
)
SELECT batch_id,domain,source_record_key,source_match_id,source_player_id,side,origin,value_json,
    kickoff_at,match_status,home_team_id,away_team_id,official_match_id,source_name,imported_at,
    normalization_version,
    CASE WHEN invalid_sequence OR (has_increase AND has_decrease) THEN NULL
        ELSE candidate_at END AS change_at,
    CASE WHEN candidate_at IS NULL OR invalid_sequence OR (has_increase AND has_decrease)
        THEN 'unresolved' ELSE candidate_basis END AS time_basis,
    CASE WHEN candidate_at IS NULL THEN candidate_reason
        WHEN invalid_sequence THEN 'invalid_group_sequence'
        WHEN has_increase AND has_decrease THEN 'inconsistent_group_order'
        ELSE candidate_reason END AS time_resolution_reason,
    CASE WHEN invalid_sequence THEN 'invalid_sequence'
        WHEN has_increase AND has_decrease THEN 'conflict'
        WHEN has_increase THEN 'ascending' WHEN has_decrease THEN 'descending'
        ELSE 'flat' END AS group_direction,
    candidate_at IS NOT NULL AND NOT invalid_sequence AND NOT (has_increase AND has_decrease)
        AS timeline_usable,
    CASE WHEN value_json->>'change_time' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
        THEN 'source_explicit_offset' ELSE 'assumed_site_Asia/Shanghai' END AS change_timezone_basis,
    'titan007-odds-year/v2'::TEXT AS time_resolution_version,
    effective_kickoff_at,kickoff_time_basis,time_evidence_url
FROM checked;

COMMENT ON VIEW football_history_odds_timeline IS
    'v2: explicit years and sparse checked evidence precede bounded missing-year inference; reference kickoff corrections remain separate from immutable source history. Timeline usability does not prove pre-match publication.';
GRANT SELECT ON football_history_odds_timeline TO fqp;
