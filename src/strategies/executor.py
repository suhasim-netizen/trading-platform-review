"""Strategy executor (Task 3 stub).

Future phase will implement sandboxed strategy execution and route execution
through the requesting tenant's registered BrokerAdapter.
"""

from __future__ import annotations


class StrategyExecutionError(RuntimeError):
    """Task-3 placeholder error type for strategy execution failures."""


async def execute_registered_strategy(*_: object, **__: object) -> tuple[object, object]:
    """Task-3 scaffolding placeholder."""
    raise NotImplementedError("Task 4/5: implement strategy execution + tenant-scoped adapter routing")

