SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';

LOCK TABLE player_registration_facts IN ACCESS EXCLUSIVE MODE;
LOCK TABLE player_registration_authority_sources IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM player_registration_facts)
       OR EXISTS (SELECT 1 FROM player_registration_authority_sources) THEN
        RAISE EXCEPTION 'registration facts or source approvals exist; keep migration 135 to preserve reviewed evidence';
    END IF;
END
$$;

DROP VIEW player_registration_eligibility_current;
DROP VIEW player_registration_authority_current;
DROP VIEW player_affiliation_candidates;
DROP TRIGGER player_registration_fact_authority_guard ON player_registration_facts;
DROP TABLE player_registration_facts;
DROP TABLE player_registration_authority_sources;
DROP FUNCTION require_approved_player_registration_authority();
DROP FUNCTION guard_player_registration_authority_revision();
DROP FUNCTION reject_player_registration_fact_mutation();
DROP FUNCTION reject_player_registration_authority_mutation();
DROP FUNCTION player_registration_evidence_refs_valid(JSONB);
