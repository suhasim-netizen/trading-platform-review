"""Tenant onboarding service stub (Task 3).

Future phase will implement tenant namespace bootstrap, secure secrets provisioning,
and sandbox environment setup with strict tenant isolation.
"""

from __future__ import annotations


def bootstrap_tenant_namespace(*_: object, **__: object) -> object:
    raise NotImplementedError("Task 4/5: implement tenant namespace bootstrap + secrets hook")


def mark_secrets_hook_dispatched(*_: object, **__: object) -> None:
    raise NotImplementedError("Task 4/5: implement secrets hook dispatch bookkeeping")

