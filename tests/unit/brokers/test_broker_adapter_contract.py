"""Sanity checks for BrokerAdapter contract (no concrete broker)."""

import inspect

from brokers.base import BrokerAdapter


def test_broker_adapter_is_abstract():
    assert inspect.isabstract(BrokerAdapter)
