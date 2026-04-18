# PAPER TRADING MODE

"""AccountRouter — resolve broker account_id per order/instrument type.

This keeps execution broker-agnostic while enabling multi-account routing for a single broker.
"""

from __future__ import annotations

from brokers.models import InstrumentType, Order
from config import get_settings


class AccountRouter:
    def resolve(self, order: Order, tenant_id: str) -> str:
        """Returns the correct account_id for this order based on instrument type."""
        if not tenant_id:
            raise ValueError("tenant_id is required")
        s = get_settings()

        match order.instrument_type:
            case InstrumentType.EQUITY:
                account_id = s.ts_equity_account_id
            case InstrumentType.OPTIONS:
                account_id = s.ts_options_account_id
            case InstrumentType.FUTURES | InstrumentType.FUTURES_OPTIONS:
                account_id = s.ts_futures_account_id
            case _:
                raise ValueError(f"unsupported instrument_type: {order.instrument_type!r}")

        if account_id:
            return account_id.strip()

        # Deprecated fallback only: never silently route unknown instruments.
        if s.ts_account_id:
            return s.ts_account_id.strip()

        raise ValueError(
            f"missing account id for instrument_type={order.instrument_type.value!r}; "
            "set TS_EQUITY_ACCOUNT_ID / TS_OPTIONS_ACCOUNT_ID / TS_FUTURES_ACCOUNT_ID"
        )



