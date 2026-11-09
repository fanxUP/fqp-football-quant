# Security review: prematch scheduling release

Mode: STRICT. Scope: all changed application, ingestion, SQL, release-policy and test files.

- Credentials: no API keys, passwords, cookies or other secrets were added.
- Network boundary: Sporttery endpoints are fixed. Official notice links must match the expected path pattern and are reconstructed on the Sporttery origin. Titan007 URLs are constructed from validated numeric match IDs; the existing acquisition client restricts destination hosts, bounds response size, timeout, request count and daily budget.
- Injection: SQL values use bound parameters. The dynamic SQL fragment in the market retry path is a fixed internal predicate; user-controlled values are not interpolated. Release migrations are selected from the migration runner's validated pending list and pinned to exact SHA-256 values.
- Authorization: no HTTP route or authentication boundary changed. The new runtime grants are limited to the two new tables and required columns. Isolated PostgreSQL rehearsal confirmed `fqp` is non-superuser and does not own the new tables; catalog read/write paths work under that role.
- Data integrity: published market references are immutable through a database trigger. Both down migrations refuse rollback while runtime records exist. No broad DELETE/TRUNCATE grant, destructive production cleanup or database-copy operation was added.
- Operations/supply chain: no dependency, SSH configuration, firewall, container privilege or global permission change. The deploy script only expands its pinned migration allowlist and validation.

Result: PASS. The isolated rehearsal used synthetic schema fixtures only and did not connect to production.
