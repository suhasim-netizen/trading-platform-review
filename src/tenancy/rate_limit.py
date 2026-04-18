# DRAFT — Pending Security Architect sign-off (P1-03)

"""In-memory per-tenant rate limiting (draft).

This is a simple fixed-window counter keyed by tenant_id.
Production will likely replace this with Redis or an API gateway policy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class FixedWindowTenantRateLimiter:
    limit: int
    window_s: int
    _buckets: dict[str, tuple[int, float]] = field(default_factory=dict)

    def allow(self, tenant_id: str) -> bool:
        if not tenant_id:
            return False
        now = time.time()
        count, start = self._buckets.get(tenant_id, (0, now))
        if now - start >= self.window_s:
            count, start = 0, now
        if count + 1 > self.limit:
            self._buckets[tenant_id] = (count, start)
            return False
        self._buckets[tenant_id] = (count + 1, start)
        return True

