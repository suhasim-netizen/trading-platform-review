# Broker factory (Phase 1 Task 6)

## Overview

The platform selects a concrete broker adapter by string key (e.g. `tradestation`) via:

- `BROKER_IMPL` in environment variables → `Settings.broker_impl`
- `src/services/broker_factory.py::build_broker_adapter(settings)` → `BrokerAdapter`

No application code outside `src/brokers/` should import concrete adapters directly.

## How adapters register

1. Create a new adapter package: `src/brokers/<vendor>/`
2. Implement `BrokerAdapter` in `src/brokers/<vendor>/adapter.py`
3. Register it from `src/brokers/<vendor>/__init__.py`:

```python
from brokers.registry import register_adapter
from .adapter import VendorAdapter

register_adapter("<vendor>", VendorAdapter)
```

4. Ensure the `brokers` package imports the vendor package for registration (composition-only):
   - `src/brokers/__init__.py` imports `.<vendor>` for its side effect.

## Adding a second broker

- Add the new package under `src/brokers/<vendor>/`
- Register it with `register_adapter("<vendor>", VendorAdapter)`
- Deploy with `BROKER_IMPL=<vendor>`

No changes should be required in strategy/OMS logic because they depend only on `BrokerAdapter`.

