# PAPER TRADING MODE

"""Strategy execution framework (tenant-scoped, event-driven).

Public surface:
- StrategyRunner
- OrderRouter
- PositionTracker
- ExecutionLogger
"""

# Match pytest.ini ``pythonpath = src`` so package imports work when executing modules directly.
import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from .logger import ExecutionLogger
from .account_router import AccountRouter
from .intraday_manager import IntradayPositionManager
from .order_tracker import OrderTracker
from .router import OrderRouter, RiskPolicy
from .platform_runner import TradingPlatform
from .runner import StrategyRunner
from .scanner import MultiSymbolScanner
from .tracker import PositionTracker

__all__ = [
    "AccountRouter",
    "ExecutionLogger",
    "IntradayPositionManager",
    "MultiSymbolScanner",
    "OrderTracker",
    "OrderRouter",
    "PositionTracker",
    "RiskPolicy",
    "StrategyRunner",
    "TradingPlatform",
]

