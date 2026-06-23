"""Position sizing.

Volatility-adjusted fixed-fractional sizing with an optional Kelly ceiling and
a reduction ladder that cuts size after losing streaks and during drawdowns.

The core idea: you decide how much *risk* (distance to your stop) you are
willing to put on per trade, expressed as a fraction of equity. From that, the
number of units follows directly. Everything else — volatility scaling, the
Kelly cap, the reduction ladder, the high-conviction bonus — only ever moves
that risk fraction up or down within hard floors and ceilings.

The notional cap is absolute: a position's notional can never exceed
``max_notional_pct`` of equity, regardless of what the risk math produces.

Alongside the class, this module offers three small, composable sizing helpers
you can reach for on their own: :func:`kelly_fraction` (the edge-optimal risk
fraction), :func:`volatility_target_size` (size a position to a target
volatility), and :func:`inverse_vol_weights` (naive risk-parity weights across a
basket). Each is a pure function with no dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass
class SizingInputs:
    """Everything the sizer needs to size a single trade.

    Prices are in quote currency; ``atr`` is the current Average True Range and
    ``atr_baseline`` is a longer-run ATR used to scale risk down when the market
    is more volatile than usual. ``drawdown_pct`` and ``daily_loss_pct`` are
    positive numbers (e.g. ``4.2`` means down 4.2%).

    The Kelly inputs (``win_rate``, ``avg_win``, ``avg_loss``) are optional. When
    all three are supplied the sizer applies a half-Kelly ceiling.
    """

    equity: float
    entry_price: float
    stop_price: float
    atr: float
    atr_baseline: float
    confluence_score: int = 100
    consecutive_losses: int = 0
    drawdown_pct: float = 0.0
    daily_loss_pct: float = 0.0
    win_rate: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None


@dataclass
class SizingResult:
    """The sized position.

    ``units`` is the position size in base units (0 means *do not trade*).
    ``multipliers_applied`` records every adjustment that fired, so the decision
    is fully auditable. When ``units`` is 0, ``reason_for_zero`` explains why.
    """

    units: float
    notional: float
    risk_amount: float
    risk_pct: float
    multipliers_applied: dict[str, float] = field(default_factory=dict)
    reason_for_zero: str | None = None


class PositionSizer:
    """Volatility-adjusted fixed-fractional position sizer.

    All percentage arguments are given as human percentages (``1.0`` == 1%) and
    stored internally as fractions.
    """

    def __init__(
        self,
        base_risk_pct: float = 1.0,
        max_risk_pct: float = 1.5,
        min_risk_pct: float = 0.25,
        max_notional_pct: float = 4.0,
        high_conviction_score: int = 85,
        high_conviction_size_mult: float = 1.5,
    ) -> None:
        self.base_risk = base_risk_pct / 100.0
        self.max_risk = max_risk_pct / 100.0
        self.min_risk = min_risk_pct / 100.0
        self.max_notional = max_notional_pct / 100.0
        self.high_conviction = high_conviction_score
        self.hc_size_mult = high_conviction_size_mult

    # ------------------------------------------------------------------ helpers

    def _reduction_multiplier(self, inputs: SizingInputs) -> tuple[float, dict[str, float]]:
        """Combine every size adjustment into a single multiplier (audited)."""
        applied: dict[str, float] = {}
        m = 1.0

        if inputs.consecutive_losses >= 3:
            applied["consecutive_losses>=3"] = 0.5
            m *= 0.5
        elif inputs.consecutive_losses == 2:
            applied["consecutive_losses==2"] = 0.75
            m *= 0.75

        dd = inputs.drawdown_pct
        if dd > 7:
            applied["drawdown>7"] = 0.25
            m *= 0.25
        elif dd > 5:
            applied["drawdown>5"] = 0.5
            m *= 0.5
        elif dd > 3:
            applied["drawdown>3"] = 0.75
            m *= 0.75

        if inputs.daily_loss_pct > 1.0:
            applied["daily_loss>1"] = 0.5
            m *= 0.5

        if 70 <= inputs.confluence_score < 75:
            applied["confluence_70_74"] = 0.75
            m *= 0.75

        if inputs.confluence_score >= self.high_conviction:
            applied["high_conviction"] = self.hc_size_mult
            m *= self.hc_size_mult

        return m, applied

    # ------------------------------------------------------------------ public

    def size(self, inputs: SizingInputs) -> SizingResult:
        """Size one trade. Returns a :class:`SizingResult`; ``units == 0`` means skip."""
        risk_per_unit = abs(inputs.entry_price - inputs.stop_price)
        if risk_per_unit <= 0 or inputs.equity <= 0:
            return SizingResult(0, 0, 0, 0, reason_for_zero="zero-distance stop or equity")

        # Volatility scaling: more vol than baseline -> smaller risk fraction.
        ratio = (inputs.atr / inputs.atr_baseline) if inputs.atr_baseline > 0 else 1.0
        ratio = max(0.2, min(5.0, ratio))
        vol_adjusted_risk = self.base_risk / ratio

        # Kelly ceiling (only if we have all three stats). A non-positive Kelly
        # fraction means no historical edge -> risk clamps toward 0 and the
        # min-risk floor below skips the trade.
        if (
            inputs.win_rate is not None
            and inputs.avg_win is not None
            and inputs.avg_loss is not None
        ):
            kelly = kelly_fraction(
                inputs.win_rate, inputs.avg_win, inputs.avg_loss, fraction=0.5
            )
            vol_adjusted_risk = min(vol_adjusted_risk, kelly)

        # Reduction ladder + ceiling.
        red_mult, applied = self._reduction_multiplier(inputs)
        risk_pct = vol_adjusted_risk * red_mult
        risk_pct = max(0.0, min(self.max_risk, risk_pct))

        if risk_pct < self.min_risk:
            return SizingResult(
                0, 0, 0, risk_pct, applied,
                reason_for_zero=f"risk {risk_pct * 100:.3f}% below floor",
            )

        risk_amount = inputs.equity * risk_pct
        units = risk_amount / risk_per_unit

        # Absolute notional cap.
        max_units_by_notional = (inputs.equity * self.max_notional) / inputs.entry_price
        if units > max_units_by_notional:
            applied["notional_cap"] = max_units_by_notional / units
            units = max_units_by_notional
            # The cap bound the size, so realized risk is now below target —
            # keep risk_pct consistent with risk_amount (risk_amount / equity).
            risk_pct = (units * risk_per_unit) / inputs.equity

        return SizingResult(
            units=units,
            notional=units * inputs.entry_price,
            risk_amount=units * risk_per_unit,
            risk_pct=risk_pct,
            multipliers_applied=applied,
        )


# ---------------------------------------------------------------------------
# Standalone, composable sizers — pure functions, no dependencies. Use them on
# their own when the stop-distance model of PositionSizer is not what you want.
# ---------------------------------------------------------------------------


def kelly_fraction(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fraction: float = 1.0,
) -> float:
    """The Kelly-optimal fraction of capital to risk, given a historical edge.

    ``win_rate`` is the win probability (0–1); ``avg_win`` and ``avg_loss`` are the
    mean win and mean loss as positive magnitudes in the same unit (e.g. R, or
    currency). Returns ``kelly · fraction`` clamped at 0 — a non-positive edge
    sizes to nothing. Pass ``fraction=0.5`` for the common, less-aggressive
    half-Kelly. Returns 0 for degenerate inputs (any of the three ≤ 0).

        kelly = win_rate − (1 − win_rate) / (avg_win / avg_loss)
    """
    if win_rate <= 0 or avg_win <= 0 or avg_loss <= 0:
        return 0.0
    payoff = avg_win / avg_loss
    kelly = win_rate - ((1.0 - win_rate) / payoff)
    return max(0.0, kelly * fraction)


def volatility_target_size(
    equity: float,
    price: float,
    return_volatility: float,
    target_volatility_pct: float,
    max_notional_pct: float = 100.0,
) -> float:
    """Units sized so a position's expected volatility ≈ a target % of equity.

    Volatility targeting sizes off an instrument's *return volatility* rather than
    a stop distance: a calmer instrument earns a larger position and a wilder one
    a smaller position, so each contributes a similar amount of risk. Supply the
    per-period return volatility as a fraction (``0.02`` == 2% σ of returns) and
    the volatility you want the position to carry, as a % of equity.

        units = (target_volatility_pct/100 · equity) / (return_volatility · price)

    The result is capped so notional never exceeds ``max_notional_pct`` of equity.
    Returns 0 for degenerate inputs (non-positive equity, price, volatility, or
    target).
    """
    if (equity <= 0 or price <= 0 or return_volatility <= 0
            or target_volatility_pct <= 0):
        return 0.0
    target_dollar_vol = (target_volatility_pct / 100.0) * equity
    per_unit_vol = return_volatility * price
    units = target_dollar_vol / per_unit_vol
    max_units = (max_notional_pct / 100.0) * equity / price
    return min(units, max_units)


def inverse_vol_weights(volatilities: Mapping[str, float]) -> dict[str, float]:
    """Risk-parity weights inversely proportional to each asset's volatility.

    The simplest form of risk parity: ignoring correlations, weighting each asset
    by 1/σ makes every position contribute the same risk. Returns weights that sum
    to 1.0. Assets with non-positive volatility are dropped; an empty or all-zero
    input returns ``{}``.
    """
    inv = {k: 1.0 / v for k, v in volatilities.items() if v > 0}
    total = sum(inv.values())
    if total <= 0:
        return {}
    return {k: w / total for k, w in inv.items()}
