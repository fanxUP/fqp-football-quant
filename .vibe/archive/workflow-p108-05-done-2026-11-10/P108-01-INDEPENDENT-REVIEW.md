# P108-01 independent review

Date: 2026-11-10 (Asia/Shanghai)
Reviewer: separate read-only reviewer agent
Scope: source-ID identity bridge, migration 134/up-down, runtime ACL, candidate report, focused tests, and CI required-module wiring.

## Result

**PASS after fixes. No remaining code or migration blocker.**

The first review found a MAJOR idempotency defect: Python compared full-precision confidence values while PostgreSQL persisted `NUMERIC(6,5)`. A repeated value could then attempt a content-free revision and be rejected by the audit trigger. The helper now validates the original range and rounds to five decimals with `ROUND_HALF_UP`, matching PostgreSQL for this non-negative range. A PostgreSQL regression reproduced the failure before the fix and passed after it.

The first review also noted two MINOR items. Concurrent first inserts now use `ON CONFLICT DO NOTHING` followed by a locked read and comparison; a barrier-controlled PostgreSQL regression reproduced the unique-key failure before the fix and now verifies two concurrent calls leave one mapping and one event. The administrator-level audit test now verifies `UPDATE`, `DELETE`, and `TRUNCATE` are all rejected by the append-only trigger. Runtime-role tests verify `INSERT`, `UPDATE`, `DELETE`, and `TRUNCATE` are denied on both mapping and event tables.

The follow-up review confirmed all findings resolved. Candidate generation remains deterministic and conservative; it never marks a row verified. Only verified mappings resolve, and API-Football compatibility is an exact `player_code` lookup when no bridge row exists. CI requires the PostgreSQL module and checks it was executed without skips.

## Verification boundary

The reviewer performed source review only. Local test evidence is recorded in `EVIDENCE.yaml`: 29 focused tests passed against marked disposable PostgreSQL 16; 10 PostgreSQL tests passed through the CI fallback DSN path; Ruff, formatting, mypy, scope, and budget passed. Exact-main GitHub CI remains pending. No production database was accessed; migration 134 was not applied to production, and no player data was imported.
