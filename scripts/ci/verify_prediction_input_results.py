"""Reject incomplete or skipped results from P105's dedicated pytest step."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

REQUIRED_MODULES = (
    "tests.test_storage.test_prediction_input_policy",
    "tests.test_computation.test_prediction_input_updates_postgres",
    "tests.test_computation.test_prediction_input_revisions_postgres",
    "tests.test_computation.test_prediction_input_fence_postgres",
    "tests.test_computation.test_prediction_input_runtime_postgres",
)
MAX_REPORT_BYTES = 16 * 1024 * 1024


def verify_report(path: Path) -> dict[str, int]:
    """Count actual testcases, not just the potentially misleading summary.

    This accepts the single-suite report emitted by our dedicated pytest call.
    Ordinary local pytest retains its optional-database behavior; only this CI
    step requires every selected module to run without a skipped testcase.
    """
    try:
        with path.open("rb") as source:
            content = source.read(MAX_REPORT_BYTES + 1)
        if len(content) > MAX_REPORT_BYTES:
            raise ValueError("report exceeds bounded size")
        root = ET.fromstring(content)
    except (OSError, ET.ParseError) as exc:
        raise ValueError("missing or malformed pytest report") from exc
    if root.tag != "testsuites" or len(root) != 1 or root[0].tag != "testsuite":
        raise ValueError("expected one dedicated pytest suite")
    suite = root[0]
    cases = suite.findall("testcase")
    try:
        total = int(suite.attrib["tests"])
        statuses = [int(suite.attrib[key]) for key in ("errors", "failures", "skipped")]
    except (KeyError, ValueError) as exc:
        raise ValueError("missing or invalid pytest counters") from exc
    if total <= 0 or total != len(cases) or any(value != 0 for value in statuses):
        raise ValueError("inconsistent, failed, errored or skipped pytest suite")
    counts = dict.fromkeys(REQUIRED_MODULES, 0)
    identities: set[tuple[str, str]] = set()
    for case in cases:
        module, name = case.get("classname", ""), case.get("name", "")
        if module not in counts or not name:
            raise ValueError("unexpected or empty testcase identity")
        if (module, name) in identities:
            raise ValueError("duplicate testcase identity")
        identities.add((module, name))
        if any(case.find(status) is not None for status in ("error", "failure", "skipped")):
            raise ValueError("a required testcase did not pass")
        counts[module] += 1
    if any(count == 0 for count in counts.values()):
        raise ValueError("missing required P105 module")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    try:
        counts = verify_report(args.report)
    except ValueError as exc:
        print(f"P105 CI rejected: {exc}", file=sys.stderr)
        return 1
    print(f"P105 CI: {sum(counts.values())} passed; all required core modules ran, no skips")
    for module, count in counts.items():
        print(f"  {module}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
