"""TradeStation-specific implementation — import only from adapter layer or registration."""

from brokers.registry import register_adapter

from .adapter import TradeStationAdapter

register_adapter("tradestation", TradeStationAdapter)

__all__ = ["TradeStationAdapter"]
