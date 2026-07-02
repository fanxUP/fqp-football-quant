# Module Contract

Every FQP module must expose:

- module_code
- module_version
- schema_version
- API routes
- scheduled jobs
- permissions
- frontend panels
- feature flags
- rollback instructions

No module may bypass audit logging, permission checks, feature flags, or the recommendation publish gate.
