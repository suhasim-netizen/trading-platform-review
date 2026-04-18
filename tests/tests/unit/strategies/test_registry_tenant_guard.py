from __future__ import annotations

import pytest

from strategies.base import StrategyMeta, StrategyOwnerKind
from strategies.registry import StrategyAccessDenied, get_strategy, register


def test_tenant_cannot_read_other_tenant_strategy():
    register(
        StrategyMeta(
            strategy_id="tenant_b_secret",
            name="secret",
            owner_kind=StrategyOwnerKind.TENANT,
            owner_id="tenant_b",
            tenant_id="tenant_b",
            code_ref="tenant_b.secret.alpha",
            params={"p": 1},
        )
    )

    with pytest.raises(StrategyAccessDenied):
        get_strategy("tenant_b_secret", caller_tenant_id="tenant_a")


def test_tenant_can_read_own_strategy():
    register(
        StrategyMeta(
            strategy_id="tenant_a_secret",
            name="secret-a",
            owner_kind=StrategyOwnerKind.TENANT,
            owner_id="tenant_a",
            tenant_id="tenant_a",
        )
    )
    meta = get_strategy("tenant_a_secret", caller_tenant_id="tenant_a")
    assert meta.tenant_id == "tenant_a"


def test_platform_strategy_visible_without_tenant_id():
    register(
        StrategyMeta(
            strategy_id="platform_1",
            name="platform",
            owner_kind=StrategyOwnerKind.PLATFORM,
            owner_id="director",
            tenant_id="should_be_stripped",
        )
    )
    meta = get_strategy("platform_1")
    assert meta.owner_kind == StrategyOwnerKind.PLATFORM
    assert meta.tenant_id is None

