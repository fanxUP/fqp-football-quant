"""FQP migration guard.

Blocks dangerous SQL patterns before Codex-generated migrations are applied.
"""

import re
import sys
from pathlib import Path

DANGEROUS_PATTERNS = [
    r"\bDROP\s+TABLE\b",
    r"\bDROP\s+COLUMN\b",
    r"\bTRUNCATE\b",
    r"\bDELETE\s+FROM\s+official_odds_snapshots\b",
    r"\bDELETE\s+FROM\s+audit_logs\b",
]


def check_sql(path: str) -> list[str]:
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    errors = []
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            errors.append(f"blocked dangerous SQL pattern {pat} in {path}")
    return errors


if __name__ == "__main__":
    all_errors = []
    for p in sys.argv[1:]:
        all_errors.extend(check_sql(p))
    if all_errors:
        raise SystemExit("\n".join(all_errors))
    print("migration guard passed")
