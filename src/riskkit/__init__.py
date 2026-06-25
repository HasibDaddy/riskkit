"""riskkit — a framework-agnostic risk-management toolkit for systematic traders.

riskkit is the layer most backtesters and trading bots leave thin: how big a
position to take, where stops live, when to cut size, what not to stack, and
when to stop trading altogether. Every component is plain Python that knows
nothing about any exchange, data provider, or backtesting framework — you feed
it numbers and it hands back auditable decisions.

Components
----------
- :class:`PositionSizer`     — volatility-adjusted sizing with a Kelly ceiling
- :class:`DrawdownManager`   — drawdown-tiered size reduction + halt
- :class:`StopEngine`        — composable stop stack (initial/BE/trail/time/vol)
- :class:`CorrelationGuard`  — one open position per correlation group
- :class:`SessionManager`    — daily limits, cooldowns, tilt detection
- :class:`PreTradeValidator` — the composable final gate before an order

Quick start::

    from riskkit import PositionSizer, SizingInputs

    sizer = PositionSizer(base_risk_pct=1.0, max_notional_pct=4.0)
    result = sizer.size(SizingInputs(
        equity=10_000, entry_price=100, stop_price=98,
        atr=2.0, atr_baseline=2.0,
    ))
    print(result.units, result.risk_pct)
"""
from __future__ import annotations

from .correlation import CorrelationDecision, CorrelationGuard
from .drawdown import DrawdownManager, DrawdownState
from .manager import OpenPosition, RiskConfig, RiskDecision, RiskManager, TradeIntent
from .metrics import conditional_value_at_risk, value_at_risk
from .session import SessionDecision, SessionManager, TradeRecord
from .sizing import (
    PositionSizer,
    SizingInputs,
    SizingResult,
    inverse_vol_weights,
    kelly_fraction,
    volatility_target_size,
)
from .stops import Side, StopEngine, StopStack
from .validator import CheckResult, PreTradeValidator, TradeProposal, ValidationResult

__version__ = "0.4.1"

__all__ = [
    # façade
    "RiskManager",
    "RiskConfig",
    "TradeIntent",
    "RiskDecision",
    "OpenPosition",
    # sizing
    "PositionSizer",
    "SizingInputs",
    "SizingResult",
    "kelly_fraction",
    "volatility_target_size",
    "inverse_vol_weights",
    # drawdown
    "DrawdownManager",
    "DrawdownState",
    # stops
    "StopEngine",
    "StopStack",
    "Side",
    # correlation
    "CorrelationGuard",
    "CorrelationDecision",
    # session
    "SessionManager",
    "SessionDecision",
    "TradeRecord",
    # validator
    "PreTradeValidator",
    "TradeProposal",
    "ValidationResult",
    "CheckResult",
    # metrics
    "value_at_risk",
    "conditional_value_at_risk",
    "__version__",
]
