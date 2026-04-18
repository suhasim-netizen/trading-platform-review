# DRAFT — Pending Security Architect sign-off (P1-03)

import pytest

from services.audit_log import InMemoryAuditLogger


def test_audit_logger_rejects_missing_tenant_id():
    log = InMemoryAuditLogger()
    with pytest.raises(ValueError):
        log.write(tenant_id="", event_type="x", metadata={})

