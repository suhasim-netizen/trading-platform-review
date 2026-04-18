"""SQLAlchemy Declarative base for ORM models.

Phase 1 uses a shared schema with row-level multi-tenancy. All tenant-owned tables
must include a non-null ``tenant_id`` that references ``tenants.tenant_id``.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass

