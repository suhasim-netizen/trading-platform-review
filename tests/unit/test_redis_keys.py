import pytest

from tenancy.redis_keys import tenant_channel, tenant_key


def test_tenant_key_prefixes():
    assert tenant_key("t1", "orders") == "t1:orders"


def test_tenant_channel_prefixes():
    assert tenant_channel("t1", "signals") == "t1:signals"


def test_tenant_key_rejects_empty():
    with pytest.raises(ValueError):
        tenant_key("", "k")
