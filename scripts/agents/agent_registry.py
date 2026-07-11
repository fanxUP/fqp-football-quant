"""Agent registry loader for FQP.

Loads agent definitions from YAML and can seed the PostgreSQL agent_registry table.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from apps.backend.src.db import get_db
from scripts.agent_storage import seed_agent_registry


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    type: str
    permission_level: str
    description: str


def load_agent_registry(path: str | Path = "configs/agent_registry.yaml") -> list[AgentDefinition]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [AgentDefinition(**item) for item in data.get("agents", [])]


def get_agent(name: str, path: str | Path = "configs/agent_registry.yaml") -> AgentDefinition:
    for agent in load_agent_registry(path):
        if agent.name == name:
            return agent
    raise KeyError(f"Agent not found: {name}")


def seed_from_yaml(
    yaml_path: str | Path = "configs/agent_registry.yaml",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Read agent_registry.yaml and seed the PostgreSQL agent_registry table.

    Idempotent — uses ON CONFLICT DO NOTHING.
    """
    agents = load_agent_registry(yaml_path)
    agent_dicts = [
        {
            "name": a.name,
            "type": a.type,
            "description": a.description,
            "permission_level": a.permission_level,
        }
        for a in agents
    ]

    if dry_run:
        return {"status": "dry_run", "would_seed": len(agent_dicts), "agents": agent_dicts}

    with get_db() as conn:
        count = seed_agent_registry(conn, agent_dicts)

    return {"status": "ok", "seeded": count, "total_in_yaml": len(agent_dicts)}
