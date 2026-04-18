"""OMS service stub (Task 3).

Future phase will implement tenant-isolated order persistence + adapter-based execution.
"""

from __future__ import annotations


class OrderManagementService:
    """Task-3 scaffolding placeholder for tenant-isolated OMS."""

    def __init__(self, *_: object, **__: object) -> None:
        pass

    def list_orders(self, *_, **__) -> list[object]:
        raise NotImplementedError("Task 4/5: implement OMS listing with strict tenant/trading_mode scoping")

    async def submit_order(self, *_, **__) -> object:
        raise NotImplementedError("Task 4/5: implement OMS submit with BrokerAdapter execution and tenant isolation")


__all__ = ["OrderManagementService"]

