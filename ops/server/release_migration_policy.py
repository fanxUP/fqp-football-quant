"""Validate release evidence before applying pending production migrations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

REVIEWED_NO_BACKUP_CHECKSUMS = {
    "127_football_fixture_seasons.sql": (
        "7c0c61920f62680e3f4951e5dd98dd57a9588f12315df1e64c570f69d725023c"
    ),
    "123_football_history_odds_invalid_timezone.sql": (
        "ba62d08357813c093a5304d9143c2e2c5e0295f010e4338afeb4d4ca65911744"
    ),
    "124_official_event_season_retention.sql": (
        "2f6de44205a6243737cb193c99ae0eaf0e011b66a8be6514388310a4c65f6d44"
    ),
    "125_football_fixture_identity.sql": (
        "9037dd6a91aca5c558b82b9aa41165f21bf4fe3f7a4fadfacdb8d3b7b0b91d10"
    ),
    "126_official_season_retention_access.sql": (
        "dc3dd7640d261eb625ecb8f4fc8a26c3562a55ffd52b99c2c54fd4d23d695ff8"
    ),
    "128_traditional_history_facts.sql": (
        "072bb16f074926911fdcb5972575dc95795e26e096c079dec1a558a64cddd9d2"
    ),
    "129_football_fixture_identity_aliases.sql": (
        "ee124b135697aa5cce79f37d9ebf7c8d96e6e4ee64918aabd3e856b4bc4e4f58"
    ),
    "130_football_fixture_result_facts.sql": (
        "be4c70ac5a61b0a3047e62dd89be7dff57bd58a16587958905284e712b671655"
    ),
    "131_prediction_statistics_rollup.sql": (
        "a98300da5bfa7ec8b1e1c21cabec83ec580a4346cb6e6835707d831706c55b1f"
    ),
    "132_prematch_prediction_schedule.sql": (
        "da80a5386d29f24f9cc1a182532c929a3c44a908e276a329e5ac1c3cd050a524"
    ),
    "133_traditional_market_reference.sql": (
        "bad49ba6686f18d9e7f6252feea3dc183dc27475e379722c6ee732c3c6f43fc7"
    ),
    "139_prediction_recovery_index.sql": (
        "de9821bebebeee26a2f2ce114dce8eb563d2429873a28a199e82601d050bb62c"
    ),
}
REVIEWED_NO_BACKUP_ROLLBACK_CHECKSUMS = {
    "131_prediction_statistics_rollup.down.sql": (
        "2b99a556dccf22e7ae181cd9a8bb9232385338483f3bf91180839e6a0329e4c3"
    ),
}
REVIEWED_NO_BACKUP_SEASONS = ["127_football_fixture_seasons.sql"]
REVIEWED_NO_BACKUP_PAIR = [
    "124_official_event_season_retention.sql",
    "125_football_fixture_identity.sql",
]
REVIEWED_NO_BACKUP_ACL = ["126_official_season_retention_access.sql"]
REVIEWED_NO_BACKUP_TRADITIONAL_FACTS = ["128_traditional_history_facts.sql"]
REVIEWED_NO_BACKUP_ALIASES = ["129_football_fixture_identity_aliases.sql"]
REVIEWED_NO_BACKUP_RESULT_FACTS = ["130_football_fixture_result_facts.sql"]
REVIEWED_NO_BACKUP_PREDICTION_STATS = ["131_prediction_statistics_rollup.sql"]
REVIEWED_NO_BACKUP_PREMATCH = [
    "132_prematch_prediction_schedule.sql",
    "133_traditional_market_reference.sql",
]
REVIEWED_NO_BACKUP_RECOVERY = ["139_prediction_recovery_index.sql"]
REVIEWED_NO_BACKUP_RECOVERY_ROLLBACK_CHECKSUMS = {
    "139_prediction_recovery_index.down.sql": (
        "3ad8b13fdaa84d7ff1aba2d92d7eb3d404c8438946064147e1ec9f44fa58ba41"
    )
}
REVIEWED_RECOVERY_QUERY_SHA256 = "2e06133c214593022a29bd22f5085853c92c48c42b3dbfa3a1260744edb48a5c"
REVIEWED_NO_BACKUP_PREMATCH_ROLLBACK_CHECKSUMS = {
    "132_prematch_prediction_schedule.down.sql": (
        "edb7843304cd0e06456cabc1f84e00f049913f9821c81e1eaa22837d4bd83cd3"
    ),
    "133_traditional_market_reference.down.sql": (
        "d3f2b66c012b022bdb1d7f607773bc2033f17cda79c64ae2603b18437d09d274"
    ),
}
NO_BACKUP_REHEARSAL_FIELD = "no_backup_migration_rehearsal"
PREMATCH_REHEARSAL_FIELD = "prematch_migration_rehearsal"
MAX_PRODUCTION_SAMPLE_MATCHES = 20
MAX_PRODUCTION_SAMPLE_ROWS_PER_TABLE = 250_000
TRUSTED_NO_BACKUP_SIGNER_PUBLIC_KEY = Path("/etc/ssh/ssh_host_ed25519_key.pub")
TRUSTED_SSH_KEYGEN = Path("/usr/bin/ssh-keygen")
NO_BACKUP_SIGNER_IDENTITY = "fqp-production-host"
NO_BACKUP_SIGNING_NAMESPACE = "fqp-p107-migration-131"
RECOVERY_SIGNING_NAMESPACE = "fqp-p105-migration-139"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _refuse(message: str) -> NoReturn:
    raise SystemExit(message)


def _verify_pinned_sql(project_root: Path, migration_names: list[str]) -> None:
    for name in migration_names:
        expected = REVIEWED_NO_BACKUP_CHECKSUMS[name]
        path = project_root / "sql" / name
        if not path.is_file():
            _refuse(f"Reviewed migration is missing from checkout: {name}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            _refuse(f"Migration checksum is outside the reviewed no-backup release: {name}")


def _verify_pinned_rollback_sql(
    project_root: Path,
    rollback_names: list[str],
    *,
    checksums: dict[str, str] | None = None,
) -> None:
    pinned_checksums = checksums or REVIEWED_NO_BACKUP_ROLLBACK_CHECKSUMS
    for name in rollback_names:
        expected = pinned_checksums[name]
        path = project_root / "sql" / "down" / name
        if not path.is_file():
            _refuse(f"Reviewed rollback migration is missing from checkout: {name}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            _refuse(
                f"Rollback migration checksum is outside the reviewed no-backup release: {name}"
            )


def _verify_signed_rehearsal(
    report_path: Path, report_bytes: bytes, *, namespace: str = NO_BACKUP_SIGNING_NAMESPACE
) -> None:
    signature_path = Path(f"{report_path}.sig")
    public_key_path = TRUSTED_NO_BACKUP_SIGNER_PUBLIC_KEY
    if (
        signature_path.is_symlink()
        or not signature_path.is_file()
        or public_key_path.is_symlink()
        or not public_key_path.is_file()
        or TRUSTED_SSH_KEYGEN.is_symlink()
        or not TRUSTED_SSH_KEYGEN.is_file()
        or not TRUSTED_SSH_KEYGEN.stat().st_mode & 0o111
    ):
        _refuse("Migration rehearsal requires a signed report from the production host")
    try:
        public_key_parts = public_key_path.read_text().strip().split()
    except OSError as exc:
        raise SystemExit("Cannot read the trusted production-host signing key") from exc
    if len(public_key_parts) < 2 or public_key_parts[0] != "ssh-ed25519":
        _refuse("Trusted production-host signing key is invalid")

    with tempfile.TemporaryDirectory(prefix="fqp-rehearsal-signers-") as temp_directory:
        allowed_signers = Path(temp_directory) / "allowed_signers"
        allowed_signers.write_text(
            f"{NO_BACKUP_SIGNER_IDENTITY} {public_key_parts[0]} {public_key_parts[1]}\n"
        )
        try:
            result = subprocess.run(
                [
                    str(TRUSTED_SSH_KEYGEN),
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed_signers),
                    "-I",
                    NO_BACKUP_SIGNER_IDENTITY,
                    "-n",
                    namespace,
                    "-s",
                    str(signature_path),
                ],
                input=report_bytes,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SystemExit("Cannot verify the production-host rehearsal signature") from exc
    if result.returncode:
        _refuse("Migration rehearsal signature is invalid or not from the production host")


def _verify_no_backup_authorization(record: dict[str, Any], pending: list[str]) -> None:
    if (
        record.get("no_backup_authorized") is not True
        or not str(record.get("no_backup_reason", "")).strip()
    ):
        _refuse("No-backup release requires explicit recorded operator authorization")
    rehearsal_field = (
        "migration_nontransactional_dry_run"
        if pending == REVIEWED_NO_BACKUP_RECOVERY
        else "migration_transaction_dry_run"
    )
    if record.get(rehearsal_field) != "passed":
        _refuse(
            "No-backup release requires a passed isolated "
            f"{'non-transactional' if rehearsal_field == 'migration_nontransactional_dry_run' else 'transaction'} migration rehearsal"
        )


def _recovery_index_state_matches(state: Any) -> bool:
    if not isinstance(state, dict):
        return False
    if (
        state.get("index_name") != "idx_ai_job_runs_prediction_recovery"
        or state.get("schema") != "public"
        or state.get("table") != "ai_job_runs"
        or state.get("method") != "btree"
        or state.get("valid") is not True
        or state.get("ready") is not True
        or state.get("attributes") != 2
        or state.get("key_attributes") != 2
    ):
        return False

    def normalize(value: Any) -> str:
        return re.sub(r'[\s()"]+', "", value).lower() if isinstance(value, str) else ""

    def normalize_predicate(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        normalized: list[str] = []
        index = 0
        in_string = False
        in_identifier = False
        while index < len(value):
            char = value[index]
            if in_string:
                normalized.append(char)
                if char == "'":
                    if index + 1 < len(value) and value[index + 1] == "'":
                        normalized.append("'")
                        index += 2
                        continue
                    in_string = False
                index += 1
                continue
            if in_identifier:
                normalized.append(char)
                if char == '"':
                    if index + 1 < len(value) and value[index + 1] == '"':
                        normalized.append('"')
                        index += 2
                        continue
                    in_identifier = False
                index += 1
                continue
            if char == "'":
                in_string = True
                normalized.append(char)
                index += 1
                continue
            if char == '"':
                in_identifier = True
                normalized.append(char)
                index += 1
                continue
            if char.isspace() or char in "()":
                index += 1
                continue
            cast_end = index + len("::text")
            if value[index:cast_end].lower() == "::text" and (
                cast_end == len(value) or not (value[cast_end].isalnum() or value[cast_end] in "_$")
            ):
                index = cast_end
                continue
            normalized.append(char.lower())
            index += 1
        return "".join(normalized)

    if normalize(state.get("first_key")) != "input_snapshot_refs->>'execution_protocol'::text":
        return False
    if normalize(state.get("second_key")) != "id":
        return False
    predicate = normalize_predicate(state.get("predicate"))
    return predicate == "job_code='model_prediction'andstatus='running'"


def _recovery_plan_uses_index(plan: Any) -> bool:
    if not isinstance(plan, list) or len(plan) != 1 or not isinstance(plan[0], dict):
        return False

    def visit(node: Any, relation_context: str | None = None) -> bool:
        if isinstance(node, dict):
            relation = node.get("Relation Name", relation_context)
            index_condition = node.get("Index Cond")
            normalized_condition = (
                re.sub(r'[\s()"]+', "", index_condition).lower()
                if isinstance(index_condition, str)
                else ""
            )
            protocol_key = "input_snapshot_refs->>'execution_protocol'::text"
            if (
                node.get("Index Name") == "idx_ai_job_runs_prediction_recovery"
                and node.get("Node Type") in ("Index Scan", "Index Only Scan", "Bitmap Index Scan")
                and relation == "ai_job_runs"
                and protocol_key in normalized_condition
                and (
                    "'prediction-session/v1'" in normalized_condition
                    or "$1" in normalized_condition
                )
            ):
                return True
            return any(visit(child, relation) for child in node.values())
        elif isinstance(node, list):
            return any(visit(child, relation_context) for child in node)
        return False

    return visit(plan[0])


def _verify_no_backup_rehearsal(
    record: dict[str, Any],
    pending: list[str],
    target_sha: str,
    evidence_directory: Path | None,
    *,
    manifest_field: str = NO_BACKUP_REHEARSAL_FIELD,
) -> None:
    if record.get("migration_copy_dry_run") != "passed":
        _refuse("Reviewed migrations require a passed isolated PostgreSQL migration copy rehearsal")
    manifest = record.get(manifest_field)
    if not isinstance(manifest, dict) or manifest.get("status") != "passed":
        _refuse("Reviewed migrations require structured no-backup PostgreSQL rehearsal evidence")
    if evidence_directory is None:
        _refuse("No-backup rehearsal evidence directory is unavailable")
    report_name = manifest.get("report_path")
    if (
        not isinstance(report_name, str)
        or not report_name
        or Path(report_name).name != report_name
        or Path(report_name).is_absolute()
    ):
        _refuse("No-backup rehearsal report must be a sibling file of the release evidence")
    report_path = evidence_directory / report_name
    if report_path.is_symlink() or not report_path.is_file():
        _refuse("No-backup rehearsal detail report is missing or unsafe")
    report_bytes = report_path.read_bytes()
    if hashlib.sha256(report_bytes).hexdigest() != manifest.get("evidence_sha256"):
        _refuse("No-backup rehearsal detail report SHA-256 mismatch")
    if pending in (REVIEWED_NO_BACKUP_PREDICTION_STATS, REVIEWED_NO_BACKUP_RECOVERY):
        namespace = (
            RECOVERY_SIGNING_NAMESPACE
            if pending == REVIEWED_NO_BACKUP_RECOVERY
            else NO_BACKUP_SIGNING_NAMESPACE
        )
        _verify_signed_rehearsal(report_path, report_bytes, namespace=namespace)
    try:
        report = json.loads(report_bytes)
    except json.JSONDecodeError as exc:
        raise SystemExit("No-backup rehearsal detail report is invalid JSON") from exc
    if not isinstance(report, dict) or report.get("status") != "passed":
        _refuse("No-backup rehearsal detail report is not marked passed")
    try:
        verified_at = datetime.fromisoformat(str(report.get("verified_at", "")))
    except ValueError as exc:
        raise SystemExit(
            "No-backup rehearsal report requires a valid verification timestamp"
        ) from exc
    if verified_at.tzinfo is None or not 0 <= (utc_now() - verified_at).total_seconds() <= 86400:
        _refuse("No-backup rehearsal report must be verified within the last 24 hours")
    if record.get("target_sha") != target_sha or report.get("target_sha") != target_sha:
        _refuse("No-backup migration rehearsal target SHA does not match the release target SHA")
    if manifest.get("pending_migrations") != pending or report.get("pending_migrations") != pending:
        _refuse("No-backup rehearsal pending migration set does not match the release plan")
    expected_checksums = {name: REVIEWED_NO_BACKUP_CHECKSUMS[name] for name in pending}
    if manifest.get("sha256") != expected_checksums:
        _refuse("No-backup rehearsal checksums do not match the reviewed migration set")
    if report.get("migration_sha256") != expected_checksums:
        _refuse("No-backup rehearsal checksums do not match the reviewed migration set")
    database = report.get("database")
    if not isinstance(database, dict) or database.get("disposable") is not True:
        _refuse("No-backup rehearsal must run in a disposable isolated PostgreSQL database")
    if not isinstance(database.get("postgres_major"), int) or database["postgres_major"] < 15:
        _refuse("No-backup rehearsal must record a supported PostgreSQL major version")
    expected_fixture_kind = (
        "targeted_production_schema_data_copy"
        if pending == REVIEWED_NO_BACKUP_PREDICTION_STATS
        else "synthetic_schema_fixture"
    )
    expected_production_copy = pending == REVIEWED_NO_BACKUP_PREDICTION_STATS
    if (
        database.get("fixture_kind") != expected_fixture_kind
        or database.get("production_data_copy") is not expected_production_copy
    ):
        _refuse("No-backup rehearsal must disclose its required fixture and production-copy scope")
    required_passes = (
        (
            "existing_rows_preserved",
            "business_rows_unchanged",
            "index_only_scope_verified",
        )
        if pending == REVIEWED_NO_BACKUP_RECOVERY
        else (
            "existing_rows_preserved",
            "constraints_and_triggers_verified",
            "transaction_rollback_verified",
        )
    )
    if any(report.get(field) != "passed" for field in required_passes):
        if pending == REVIEWED_NO_BACKUP_RECOVERY:
            _refuse(
                "No-backup recovery-index rehearsal is missing row-preservation or index-only scope proof"
            )
        _refuse("No-backup rehearsal is missing isolation, preservation, schema, or rollback proof")
    timeouts = report.get("timeouts")
    expected_timeouts = (
        {"lock_seconds": 5, "statement_seconds": 900}
        if pending == REVIEWED_NO_BACKUP_RECOVERY
        else {"lock_seconds": 2, "statement_seconds": 30}
    )
    if not isinstance(timeouts, dict) or timeouts != expected_timeouts:
        lock_seconds = expected_timeouts["lock_seconds"]
        statement_seconds = expected_timeouts["statement_seconds"]
        _refuse(
            "No-backup rehearsal must confirm the migration runner's "
            f"{lock_seconds}-second lock and {statement_seconds}-second statement timeouts"
        )
    results = report.get("test_results")
    if not isinstance(results, dict) or not (
        type(results.get("passed")) is int
        and results["passed"] > 0
        and type(results.get("failed")) is int
        and results["failed"] == 0
        and type(results.get("skipped")) is int
        and results["skipped"] == 0
    ):
        _refuse("No-backup rehearsal must record executed passing tests with no failures or skips")
    if pending == REVIEWED_NO_BACKUP_ACL:
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
            or role.get("owns_retention_table") is not False
        ):
            _refuse(
                "ACL repair rehearsal must use the restricted non-owner application runtime role"
            )
        if any(
            report.get(field) != "passed"
            for field in (
                "application_role_acl",
                "application_business_paths",
                "acl_rollback_verified",
            )
        ):
            _refuse(
                "ACL repair requires runtime grants, application business paths and ACL rollback proof"
            )

    if pending == REVIEWED_NO_BACKUP_SEASONS:
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
            or role.get("owns_season_identity_tables") is not False
        ):
            _refuse(
                "Season identity rehearsal must use the restricted non-owner application runtime role"
            )
        if any(
            report.get(field) != "passed"
            for field in (
                "application_role_acl",
                "application_business_paths",
                "acl_rollback_verified",
            )
        ):
            _refuse(
                "Season identity requires application ACL, business paths and ACL rollback proof"
            )

    if pending == REVIEWED_NO_BACKUP_TRADITIONAL_FACTS:
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
        ):
            _refuse(
                "Traditional history rehearsal must use the restricted non-superuser fqp application role"
            )
        if any(
            report.get(field) != "passed"
            for field in (
                "application_role_catalog_access",
                "application_catalog_read_path",
                "application_import_write_path",
            )
        ):
            _refuse(
                "Traditional history requires runtime-role catalog access, catalog read and import write proof"
            )

    if pending == REVIEWED_NO_BACKUP_ALIASES:
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
            or role.get("owns_alias_table") is not False
        ):
            _refuse(
                "Fixture alias rehearsal must use the restricted non-owner application runtime role"
            )
        if any(
            report.get(field) != "passed"
            for field in (
                "application_role_acl",
                "application_alias_insert_and_read_path",
                "application_alias_rollback_verified",
            )
        ):
            _refuse(
                "Fixture alias migration requires runtime ACL, alias read/write path and rollback proof"
            )

    if pending == REVIEWED_NO_BACKUP_RESULT_FACTS:
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
            or role.get("owns_result_fact_table") is not False
        ):
            _refuse("Result fact rehearsal must use the restricted non-owner fqp runtime role")
        if any(
            report.get(field) != "passed"
            for field in (
                "application_role_acl",
                "result_fact_insert_and_model_read",
                "source_fixture_mismatch_rejected",
                "append_only_enforced",
                "result_fact_rollback_verified",
            )
        ):
            _refuse(
                "Result fact migration requires runtime ACL, source binding, model read and rollback proof"
            )

    if pending == REVIEWED_NO_BACKUP_PREDICTION_STATS:
        _verify_prediction_statistics_rehearsal(report)

    if pending == REVIEWED_NO_BACKUP_PREMATCH:
        expected_down = REVIEWED_NO_BACKUP_PREMATCH_ROLLBACK_CHECKSUMS
        if report.get("down_migration_sha256") != expected_down:
            _refuse("Prematch scheduling rehearsal rollback checksums do not match")
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
            or role.get("owns_new_tables") is not False
        ):
            _refuse("Prematch migration rehearsal must use the restricted non-owner fqp role")
        for field in (
            "application_role_acl",
            "application_business_paths",
            "published_reference_protection",
            "rollback_preserves_runtime_data",
        ):
            if report.get(field) != "passed":
                _refuse(f"Prematch migration rehearsal is missing {field} evidence")

    if pending == REVIEWED_NO_BACKUP_RECOVERY:
        if report.get("down_migration_sha256") != REVIEWED_NO_BACKUP_RECOVERY_ROLLBACK_CHECKSUMS:
            _refuse("P105 recovery index rehearsal rollback checksum does not match")
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
            or role.get("owns_ai_job_runs") is not False
        ):
            _refuse("P105 recovery index rehearsal requires the restricted non-owner fqp role")
        for field in (
            "application_role_acl",
            "recovery_owner_semantics",
            "recovery_query_plan_uses_index",
            "index_definition_verified",
            "index_valid_ready",
            "rollback_removed_index",
            "reapply_valid_ready",
        ):
            if report.get(field) != "passed":
                _refuse(f"P105 recovery index rehearsal is missing {field} evidence")
        if report.get("index_name") != "idx_ai_job_runs_prediction_recovery":
            _refuse("P105 recovery index rehearsal used an unexpected index name")
        if report.get("recovery_query_plan_role") != "fqp":
            _refuse("P105 recovery query plan must be measured as the restricted fqp role")
        if report.get("recovery_query_sha256") != REVIEWED_RECOVERY_QUERY_SHA256:
            _refuse("P105 recovery query SHA-256 does not match the reviewed owner query")
        if report.get("recovery_query_parameters") != {
            "execution_protocol": "prediction-session/v1"
        }:
            _refuse("P105 recovery query plan must use the reviewed execution protocol")
        if not _recovery_plan_uses_index(report.get("recovery_query_plan")):
            _refuse("P105 recovery query plan does not show an index scan using the pinned index")
        if not _recovery_index_state_matches(report.get("index_state")):
            _refuse("P105 recovery index catalog state does not match the pinned valid index")
        if report.get("rollback_index_state") != {"exists": False}:
            _refuse("P105 recovery DOWN rehearsal did not prove the index was removed")
        if not _recovery_index_state_matches(report.get("reapply_index_state")):
            _refuse("P105 recovery reapply did not recreate the pinned valid index")
        for field in (
            "migration_up_seconds",
            "migration_down_seconds",
            "migration_max_lock_wait_ms",
        ):
            value = report.get(field)
            if (
                type(value) not in (int, float)
                or (isinstance(value, float) and not math.isfinite(value))
                or value < 0
            ):
                _refuse(f"P105 recovery index rehearsal requires a valid {field} measurement")
        if (
            report["migration_up_seconds"] > 900
            or report["migration_down_seconds"] > 900
            or report["migration_max_lock_wait_ms"] > 5000
        ):
            _refuse("P105 recovery index rehearsal exceeded the concurrent-index timeout")


def _verify_prediction_statistics_rehearsal(report: dict[str, Any]) -> None:
    database = report["database"]
    schema_sha256 = database.get("schema_sha256")
    source_revision = database.get("source_revision")
    production_copy_at = database.get("production_copy_at")
    if (
        not isinstance(schema_sha256, str)
        or len(schema_sha256) != 64
        or any(character not in "0123456789abcdef" for character in schema_sha256)
        or not isinstance(source_revision, str)
        or len(source_revision) != 40
        or any(character not in "0123456789abcdef" for character in source_revision)
    ):
        _refuse(
            "Prediction statistics rehearsal requires production schema and source revision fingerprints"
        )
    try:
        copied_at = datetime.fromisoformat(str(production_copy_at))
    except ValueError as exc:
        raise SystemExit(
            "Prediction statistics rehearsal requires a valid production-copy timestamp"
        ) from exc
    if copied_at.tzinfo is None or not 0 <= (utc_now() - copied_at).total_seconds() <= 86400:
        _refuse("Prediction statistics production copy must be verified within the last 24 hours")

    tables = database.get("tables")
    required_tables = {
        "official_matches",
        "model_predictions",
        "model_prediction_groups",
        "model_prediction_group_options",
        "model_prediction_runs",
        "model_versions",
    }
    if not isinstance(tables, dict) or not required_tables.issubset(tables):
        _refuse("Prediction statistics rehearsal is missing a required production table copy")

    fully_copied_tables = (
        "official_matches",
        "model_prediction_runs",
        "model_versions",
    )
    for table_name in fully_copied_tables:
        table = tables.get(table_name)
        if (
            not isinstance(table, dict)
            or table.get("copy_mode") != "full"
            or type(table.get("source_rows")) is not int
            or table["source_rows"] <= 0
            or type(table.get("copied_rows")) is not int
            or table.get("copied_rows") != table.get("source_rows")
        ):
            _refuse(f"Prediction statistics rehearsal requires a complete {table_name} copy")

    prediction_table = tables.get("model_predictions")
    sample_match_ids = (
        prediction_table.get("sample_match_ids") if isinstance(prediction_table, dict) else None
    )
    if (
        not isinstance(prediction_table, dict)
        or prediction_table.get("copy_mode") != "indexed_match_sample"
        or type(prediction_table.get("source_rows_estimate")) is not int
        or prediction_table["source_rows_estimate"] <= 0
        or type(prediction_table.get("copied_rows")) is not int
        or prediction_table["copied_rows"] <= 0
        or prediction_table["copied_rows"] >= prediction_table["source_rows_estimate"]
        or prediction_table["copied_rows"] > MAX_PRODUCTION_SAMPLE_ROWS_PER_TABLE
        or not isinstance(sample_match_ids, list)
        or not sample_match_ids
        or len(sample_match_ids) > MAX_PRODUCTION_SAMPLE_MATCHES
        or any(type(match_id) is not int or match_id <= 0 for match_id in sample_match_ids)
        or len(sample_match_ids) != len(set(sample_match_ids))
    ):
        _refuse("Prediction statistics rehearsal requires an indexed production prediction sample")

    for table_name in ("model_prediction_groups", "model_prediction_group_options"):
        table = tables.get(table_name)
        table_match_ids = table.get("sample_match_ids") if isinstance(table, dict) else None
        if (
            not isinstance(table, dict)
            or table.get("copy_mode") != "matched_sample"
            or type(table.get("source_rows_estimate")) is not int
            or table["source_rows_estimate"] <= 0
            or type(table.get("copied_rows")) is not int
            or table["copied_rows"] <= 0
            or table["copied_rows"] >= table["source_rows_estimate"]
            or table["copied_rows"] > MAX_PRODUCTION_SAMPLE_ROWS_PER_TABLE
            or not isinstance(table_match_ids, list)
            or not table_match_ids
            or any(type(match_id) is not int or match_id <= 0 for match_id in table_match_ids)
            or len(table_match_ids) != len(set(table_match_ids))
            or not set(table_match_ids).issubset(set(sample_match_ids))
        ):
            _refuse(
                f"Prediction statistics rehearsal requires matched production rows from {table_name}"
            )

    queue_seed = report.get("dirty_queue_seed_matches")
    if type(queue_seed) is not int or queue_seed != tables["official_matches"]["copied_rows"]:
        _refuse("Prediction statistics rehearsal queue seed must cover every copied official match")
    for field in (
        "source_trigger_invalidation",
        "application_role_acl",
        "runtime_trigger_write_and_read",
        "down_migration_source_preservation",
        "down_migration_reapplication",
    ):
        if report.get(field) != "passed":
            _refuse(f"Prediction statistics rehearsal is missing {field} proof")

    role = report.get("application_role")
    if (
        not isinstance(role, dict)
        or role.get("name") != "fqp"
        or role.get("superuser") is not False
        or role.get("owns_rollup_tables") is not False
    ):
        _refuse("Prediction statistics rehearsal must verify the restricted non-owner fqp role")

    for field in (
        "migration_up_seconds",
        "migration_down_seconds",
        "migration_lock_wait_ms",
        "batch_refresh_seconds",
    ):
        value = report.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            _refuse(f"Prediction statistics rehearsal requires a non-negative {field} measurement")
    if (
        type(report.get("batch_refresh_rows_read")) is not int
        or report["batch_refresh_rows_read"] <= 0
    ):
        _refuse("Prediction statistics rehearsal requires a measured non-empty refresh batch")
    expected_down = {
        name: REVIEWED_NO_BACKUP_ROLLBACK_CHECKSUMS[name]
        for name in REVIEWED_NO_BACKUP_ROLLBACK_CHECKSUMS
    }
    if report.get("down_migration_sha256") != expected_down:
        _refuse(
            "Prediction statistics rehearsal rollback checksum does not match the reviewed down migration"
        )


def _validate_no_backup(
    record: dict[str, Any],
    pending: list[str],
    target_sha: str,
    project_root: Path,
    evidence_directory: Path | None,
) -> None:
    if pending == ["123_football_history_odds_invalid_timezone.sql"]:
        _verify_no_backup_authorization(record, pending)
        _verify_pinned_sql(project_root, pending)
        return
    if pending in (
        REVIEWED_NO_BACKUP_PAIR,
        REVIEWED_NO_BACKUP_ACL,
        REVIEWED_NO_BACKUP_SEASONS,
        REVIEWED_NO_BACKUP_TRADITIONAL_FACTS,
        REVIEWED_NO_BACKUP_ALIASES,
        REVIEWED_NO_BACKUP_RESULT_FACTS,
        REVIEWED_NO_BACKUP_PREDICTION_STATS,
        REVIEWED_NO_BACKUP_PREMATCH,
        REVIEWED_NO_BACKUP_RECOVERY,
    ):
        _verify_no_backup_authorization(record, pending)
        _verify_pinned_sql(project_root, pending)
        if pending == REVIEWED_NO_BACKUP_PREDICTION_STATS:
            _verify_pinned_rollback_sql(
                project_root,
                list(REVIEWED_NO_BACKUP_ROLLBACK_CHECKSUMS),
            )
        if pending == REVIEWED_NO_BACKUP_PREMATCH:
            _verify_pinned_rollback_sql(
                project_root,
                list(REVIEWED_NO_BACKUP_PREMATCH_ROLLBACK_CHECKSUMS),
                checksums=REVIEWED_NO_BACKUP_PREMATCH_ROLLBACK_CHECKSUMS,
            )
        if pending == REVIEWED_NO_BACKUP_RECOVERY:
            _verify_pinned_rollback_sql(
                project_root,
                list(REVIEWED_NO_BACKUP_RECOVERY_ROLLBACK_CHECKSUMS),
                checksums=REVIEWED_NO_BACKUP_RECOVERY_ROLLBACK_CHECKSUMS,
            )
        _verify_no_backup_rehearsal(
            record,
            pending,
            target_sha,
            evidence_directory,
            manifest_field=(
                PREMATCH_REHEARSAL_FIELD
                if pending == REVIEWED_NO_BACKUP_PREMATCH
                else NO_BACKUP_REHEARSAL_FIELD
            ),
        )
        return
    _refuse(
        "No-backup release is restricted to reviewed pinned migration sets 123, 124+125, 126, 127, 128, 129, 130, 131, the exact 132+133 prematch pair, or migration 139"
    )


def _validate_backup(
    record: dict[str, Any],
    pending: list[str],
    target_sha: str,
    project_root: Path,
    evidence_directory: Path | None,
) -> None:
    prematch_migrations = set(REVIEWED_NO_BACKUP_PREMATCH)
    if prematch_migrations.intersection(pending) and pending != REVIEWED_NO_BACKUP_PREMATCH:
        _refuse(
            "Migrations 132+133 must be the exact ordered pair with the prematch rehearsal evidence"
        )
    if record.get("migration_copy_dry_run") != "passed":
        _refuse("Pending migrations require a passed migration copy rehearsal")
    backup_path = record.get("backup_path")
    if not isinstance(backup_path, str) or not backup_path:
        _refuse("Pending migrations require a verified pre-deployment backup")
    backup = Path(backup_path)
    try:
        age = utc_now().timestamp() - backup.stat().st_mtime
    except OSError as exc:
        raise SystemExit("Pending migrations require an accessible pre-deployment backup") from exc
    if not 0 <= age <= 3600:
        _refuse("Pending migrations require a recent pre-deployment backup")
    with backup.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if checksum != record.get("backup_sha256"):
        _refuse("Backup checksum mismatch")
    try:
        subprocess.run(
            ["pg_restore", "--list", str(backup)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("Backup archive validation failed") from exc
    if pending == REVIEWED_NO_BACKUP_PREMATCH:
        _verify_pinned_sql(project_root, pending)
        _verify_pinned_rollback_sql(
            project_root,
            list(REVIEWED_NO_BACKUP_PREMATCH_ROLLBACK_CHECKSUMS),
            checksums=REVIEWED_NO_BACKUP_PREMATCH_ROLLBACK_CHECKSUMS,
        )
        _verify_no_backup_rehearsal(
            record,
            pending,
            target_sha,
            evidence_directory,
            manifest_field=PREMATCH_REHEARSAL_FIELD,
        )


def validate_release_migrations(
    record: dict[str, Any],
    release_mode: str,
    pending: list[str],
    target_sha: str,
    *,
    project_root: Path,
    evidence_directory: Path | None = None,
) -> None:
    """Fail closed unless pending migrations meet the selected release policy."""
    if not pending:
        return
    if release_mode == "--apply-no-backup":
        _validate_no_backup(record, pending, target_sha, project_root, evidence_directory)
    elif release_mode == "--apply":
        _validate_backup(record, pending, target_sha, project_root, evidence_directory)
    else:
        _refuse(f"Unsupported migration release mode: {release_mode}")


def validate_release_file(
    evidence_path: Path,
    release_mode: str,
    pending: list[str],
    target_sha: str,
    *,
    project_root: Path,
) -> None:
    try:
        record = json.loads(evidence_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("Migration release evidence is unreadable") from exc
    if not isinstance(record, dict):
        _refuse("Migration release evidence must be a JSON object")
    validate_release_migrations(
        record,
        release_mode,
        pending,
        target_sha,
        project_root=project_root,
        evidence_directory=evidence_path.parent,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("release_mode", choices=("apply", "apply-no-backup"))
    parser.add_argument("pending_json")
    parser.add_argument("target_sha")
    args = parser.parse_args()
    try:
        pending = json.loads(args.pending_json)
    except json.JSONDecodeError as exc:
        parser.error(f"pending migration list is invalid JSON: {exc}")
    if not isinstance(pending, list) or any(not isinstance(name, str) for name in pending):
        parser.error("pending migration list must be a JSON array of filenames")
    validate_release_file(
        args.evidence,
        f"--{args.release_mode}",
        pending,
        args.target_sha,
        project_root=Path.cwd(),
    )
    print("Migration release policy passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
