-- Preserve v2 results while isolating malformed source timezone offsets.
-- Do not rewrite the previously applied122 migration or any published history.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

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
        EXCEPTION WHEN invalid_time_zone_displacement_value THEN
            candidate_reason := 'invalid_timezone_offset';
        WHEN datetime_field_overflow OR invalid_datetime_format OR invalid_parameter_value THEN
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
