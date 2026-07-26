"""Retry critical idempotent jobs that may be missed while services start."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass
class _TaskState:
    attempts: int = 0
    next_attempt_at: datetime | None = None
    completed: bool = False


class StartupRecovery:
    """Run independent startup tasks with bounded exponential backoff."""

    def __init__(
        self,
        tasks: Mapping[str, Callable[[], Any]],
        *,
        retry_delays: tuple[int, ...] = (60, 120, 300, 600, 900),
    ) -> None:
        if not retry_delays or any(delay <= 0 for delay in retry_delays):
            raise ValueError("retry_delays must contain positive seconds")
        self._tasks = dict(tasks)
        self._states = {name: _TaskState() for name in self._tasks}
        self._retry_delays = retry_delays

    def run(self, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now().astimezone()
        attempted: list[str] = []
        completed: list[str] = []
        errors: dict[str, str] = {}

        for name, task in self._tasks.items():
            state = self._states[name]
            if state.completed or (state.next_attempt_at and current < state.next_attempt_at):
                continue

            attempted.append(name)
            state.attempts += 1
            try:
                result = task()
                status = (
                    str(result.get("status", "ok")).lower() if isinstance(result, dict) else "ok"
                )
                if status in {"error", "failed", "blocked"}:
                    raise RuntimeError(str(result.get("error") or result.get("message") or result))
            except Exception as exc:
                delay_index = min(state.attempts - 1, len(self._retry_delays) - 1)
                state.next_attempt_at = current + timedelta(seconds=self._retry_delays[delay_index])
                errors[name] = str(exc)
                continue

            state.completed = True
            state.next_attempt_at = None
            completed.append(name)

        pending = [name for name, state in self._states.items() if not state.completed]
        return {
            "status": "completed" if not pending else "recovering",
            "attempted": attempted,
            "completed": completed,
            "pending": pending,
            "errors": errors,
        }
