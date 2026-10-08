-- Additive only: keep all existing keys, connection identities and bindings.
ALTER TABLE llm_provider_configs ADD COLUMN IF NOT EXISTS auth_type VARCHAR(16) NOT NULL DEFAULT 'api_key';
ALTER TABLE llm_provider_configs ADD COLUMN IF NOT EXISTS api_protocol VARCHAR(64);
ALTER TABLE llm_provider_configs ADD COLUMN IF NOT EXISTS pi_credential_encrypted TEXT;
-- Existing native Ollama connections did not require credentials.
UPDATE llm_provider_configs SET auth_type = 'none' WHERE provider_code = 'ollama' AND auth_type = 'api_key' AND pi_credential_encrypted IS NULL;
