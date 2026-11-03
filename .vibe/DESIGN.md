# Design: aggregate candidate verification

Keep all development on `main`. Preserve each original P107/P138 scope lock and its archived evidence. The 54 original mapped files plus three P107 release-gate files are staged explicitly; the unowned `uv.lock` is never included.

The current candidate is verified in layers: targeted fixed-sample and isolated PostgreSQL regressions; frontend tests, typecheck and build; whole-repository Ruff/Mypy checks; independent aggregate and migration review; exact-head GitHub CI; then a current production schema and migration-relevant data-copy rehearsal. Avoid full copies of unrelated large tables. The no-backup migration 131 path remains fail-closed until the targeted production-copy evidence is signed by the production host, pinned up/down SQL hashes, role grants, queue seed, bounded refresh and source-preserving rollback are recorded. Only after those gates may production migration/deployment proceed.

Migration 131 creates rebuildable dirty-match and per-match rollup tables, uses bounded batches, and preserves the prior published snapshot while work remains. The production rehearsal must measure lock wait, initial queue size, batch time and `fqp` role permissions, and exercise the documented recovery path.
