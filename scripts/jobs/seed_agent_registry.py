"""One-shot job: seed agent_registry table from YAML config.

Idempotent — safe to run multiple times (ON CONFLICT DO NOTHING).
Runs once at scheduler startup.
"""

from __future__ import annotations

from typing import Any

from scripts.agents.agent_registry import seed_from_yaml


def run(dry_run: bool = False) -> dict[str, Any]:
    """Seed the agent_registry table from configs/agent_registry.yaml."""
    return seed_from_yaml(dry_run=dry_run)


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
