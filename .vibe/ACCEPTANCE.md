# Acceptance

- A1: Official pi-ai supplies model directory and all enabled model invocations; compatible custom models work through Pi.
- A2: Existing configurations/keys/bindings are preserved; secrets are encrypted, omitted from APIs and logs; credential rotation cannot race.
- A3: Only advertised OAuth providers can login; sessions are bounded, expire/cancel, belong to the initiating app session; failed login retains old credential.
- A4: Search/select supplier and models; display capabilities; API Key/login and verification/binding are usable with stale-response guards and keyboard/mobile support.
- A5: Targeted tests/static/build checks pass with explicit evidence and install/rollback instructions. No financial correction. Publication and deployment authorized 2026-10-08; release requires successful Linux CI, copy migration rehearsal, fresh backup, service and protected HTTP checks, and exact GitHub main/server SHA agreement.
