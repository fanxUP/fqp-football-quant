-- Project missing years at read time; published source history remains immutable.
-- There is no table rewrite, additional store or external request.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

CREATE FUNCTION football_history_odds_time_candidate(raw_time TEXT, kickoff TIMESTAMPTZ)
RETURNS TABLE(candidate_at TIMESTAMPTZ, candidate_basis TEXT, candidate_reason TEXT)
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE ROWS 1 AS $$
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
            IF possible BETWEEN kickoff-INTERVAL '4320 hours' AND kickoff+INTERVAL '12 hours' THEN
                candidate_at := possible;
                candidate_basis := 'source_full';
                candidate_reason := 'source_full_time';
            ELSE
                candidate_reason := 'outside_match_window';
            END IF;
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

CREATE VIEW football_history_odds_timeline AS
WITH candidates AS (
    SELECT h.*,p.*,
        h.value_json->>'company_id' AS company_key,
        h.value_json->>'odds_type' AS market_key,
        h.value_json->>'source' AS feed_key,
        CASE WHEN h.value_json->>'seq' ~ '^[1-9][0-9]{0,8}$'
            THEN (h.value_json->>'seq')::BIGINT END AS seq
    FROM football_history_available h
    CROSS JOIN LATERAL football_history_odds_time_candidate(h.value_json->>'change_time',h.kickoff_at) p
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
    'titan007-odds-year/v1'::TEXT AS time_resolution_version
FROM checked;

COMMENT ON VIEW football_history_odds_timeline IS
    'Derived year projection, not verified historical availability: unique year in kickoff -180d/+12h; group sequence must be monotonic. Source JSON stays unchanged. Inferred years and assumed site timezone are explicit.';
GRANT SELECT ON football_history_odds_timeline TO fqp;
