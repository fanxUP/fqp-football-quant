"""Build a deterministic, file-only review queue for external player IDs."""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

OUTPUT_FIELDS = (
    "source_name",
    "external_player_id",
    "source_player_name",
    "source_birth_date",
    "evidence_ref",
    "candidate_player_id",
    "candidate_player_name",
    "candidate_birth_date",
    "match_basis",
    "candidate_count",
    "mapping_status",
    "requires_manual_review",
)
_SOURCE_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


def _name_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _display_name(value: Any) -> str:
    return " ".join(value.strip().split()) if isinstance(value, str) else ""


def _birth_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError("birth_date values must be ISO date strings or empty")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise ValueError(f"invalid ISO birth date: {value!r}") from None


def _player_id(value: Any) -> tuple[int, str]:
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"invalid canonical player ID: {value!r}") from None
    if result <= 0:
        raise ValueError(f"invalid canonical player ID: {value!r}")
    return result, str(result)


def _required_text(row: Mapping[str, Any], key: str, *, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} requires non-empty {key}")
    return value.strip()


def build_candidate_rows(
    source_rows: Iterable[Mapping[str, Any]], canonical_rows: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Suggest exact-name matches while keeping every result unverified for human review."""
    sources: list[dict[str, Any]] = []
    seen_source_keys: set[tuple[str, str]] = set()
    for raw in source_rows:
        source_name = _required_text(raw, "source_name", label="source row").casefold()
        if not _SOURCE_NAME.fullmatch(source_name):
            raise ValueError("source_name must be a lowercase ASCII source key")
        external_id = _required_text(raw, "external_player_id", label="source row")
        player_name = _display_name(_required_text(raw, "player_name", label="source row"))
        evidence_ref = _required_text(raw, "evidence_ref", label="source row")
        if len(external_id) > 128 or len(evidence_ref) > 1024:
            raise ValueError(
                "source identity or evidence reference exceeds the documented size limit"
            )
        key = (source_name, external_id)
        if key in seen_source_keys:
            raise ValueError(f"duplicate source identity: {source_name}:{external_id}")
        seen_source_keys.add(key)
        sources.append(
            {
                "source_name": source_name,
                "external_player_id": external_id,
                "player_name": player_name,
                "name_key": _name_key(player_name),
                "birth_date": _birth_date(raw.get("birth_date")),
                "evidence_ref": evidence_ref,
            }
        )

    canonicals: list[dict[str, Any]] = []
    seen_player_ids: set[int] = set()
    for raw in canonical_rows:
        numeric_id, player_id = _player_id(raw.get("player_id"))
        if numeric_id in seen_player_ids:
            raise ValueError(f"duplicate canonical player ID: {player_id}")
        seen_player_ids.add(numeric_id)
        player_name = _display_name(_required_text(raw, "player_name", label="canonical row"))
        canonicals.append(
            {
                "numeric_id": numeric_id,
                "player_id": player_id,
                "player_name": player_name,
                "name_key": _name_key(player_name),
                "birth_date": _birth_date(raw.get("birth_date")),
            }
        )

    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for canonical in canonicals:
        if canonical["name_key"]:
            by_name[canonical["name_key"]].append(canonical)

    results: list[dict[str, Any]] = []
    for source in sources:
        same_name = by_name.get(source["name_key"], [])
        selected: list[dict[str, Any]]
        if not same_name:
            selected = []
            basis = "no_exact_name_candidate"
            status = "unresolved"
        else:
            exact_birth = [
                item
                for item in same_name
                if source["birth_date"] and item["birth_date"] == source["birth_date"]
            ]
            missing_birth = [
                item for item in same_name if not source["birth_date"] or not item["birth_date"]
            ]
            if exact_birth:
                selected = exact_birth
                basis = "exact_name_and_birth_date"
                status = "candidate"
            elif missing_birth:
                selected = missing_birth
                basis = "exact_name_birth_date_missing"
                status = "candidate"
            else:
                selected = same_name
                basis = "birth_date_conflict"
                status = "unresolved"
            if len(selected) > 1 and status == "candidate":
                basis = f"ambiguous_{basis}"
                status = "unresolved"

        count = len(selected)
        candidates_to_emit: list[dict[str, Any] | None] = []
        candidates_to_emit.extend(selected)
        if not candidates_to_emit:
            candidates_to_emit.append(None)
        for candidate in candidates_to_emit:
            results.append(
                {
                    "source_name": source["source_name"],
                    "external_player_id": source["external_player_id"],
                    "source_player_name": source["player_name"],
                    "source_birth_date": source["birth_date"],
                    "evidence_ref": source["evidence_ref"],
                    "candidate_player_id": candidate["player_id"] if candidate else "",
                    "candidate_player_name": candidate["player_name"] if candidate else "",
                    "candidate_birth_date": candidate["birth_date"] if candidate else "",
                    "match_basis": basis,
                    "candidate_count": count,
                    "mapping_status": status,
                    "requires_manual_review": True,
                    "_numeric_candidate_id": candidate["numeric_id"] if candidate else 0,
                }
            )

    results.sort(
        key=lambda row: (
            row["source_name"],
            row["external_player_id"],
            row["_numeric_candidate_id"],
        )
    )
    for row in results:
        row.pop("_numeric_candidate_id")
    return results


def read_csv(path: Path, required_fields: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or any(
            name not in reader.fieldnames for name in required_fields
        ):
            raise ValueError(f"{path} must include columns: {', '.join(required_fields)}")
        return list(reader)


def write_candidate_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-csv", type=Path, required=True)
    parser.add_argument("--canonical-csv", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_csv.resolve()
    if output in {args.source_csv.resolve(), args.canonical_csv.resolve()}:
        parser.error("output CSV must not overwrite an input file")
    source_rows = read_csv(
        args.source_csv,
        ("source_name", "external_player_id", "player_name", "birth_date", "evidence_ref"),
    )
    canonical_rows = read_csv(args.canonical_csv, ("player_id", "player_name", "birth_date"))
    write_candidate_csv(output, build_candidate_rows(source_rows, canonical_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
