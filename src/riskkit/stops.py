"""Stop engine.

Every open position carries a *stack* of stops at once; the tightest one
relative to current price is active. Stops only ever move closer to price,
never further away.

Stop types in the stack:
    initial          set at entry, never widens
    breakeven        activated at 1R profit (with a fee buffer)
    trailing_atr     activated at ``trailing_start_at_r``, trails N*ATR behind price
    trailing_ema     optional, trails a slow EMA (useful for trend trades)
    chandelier       optional, trails N*ATR from the highest high / lowest low since entry
    structure        optional, ratchets to a swing level you supply (tighten-only)
    psar             optional, ratchets to a Parabolic SAR value you supply (tighten-only)
    time             exit after N bars if the trade hasn't reached 1R
    volatility       exit if ATR spikes past ``volatility_exit_threshold`` x baseline
    rsi              for mean-reversion: exit if a momentum signal re-extremes

The chandelier, structure, and psar stops follow riskkit's "you feed it numbers"
rule: structure and psar simply trail to the level you pass in each bar, and the
chandelier anchors to the running high/low the engine tracks for you. All three
are tighten-only, like every other stop here.

The engine is pure arithmetic — it takes prices and indicator values you supply
and returns an exit reason (or ``None``). It never talks to an exchange.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Side = Literal["long", "short"]


@dataclass
class StopStack:
    """Per-position stop state. Create one at entry, then feed it to
    :meth:`StopEngine.update` once per bar."""

    side: Side
    entry_price: float
    initial: float
    breakeven: float | None = None
    trailing_atr: float | None = None
    trailing_ema: float | None = None
    chandelier: float | None = None
    structure: float | None = None
    psar: float | None = None
    time_stop_bars: int | None = None
    rsi_stop: bool = False
    use_chandelier: bool = False
    volatility_baseline: float | None = None
    volatility_threshold: float = 2.0
    bars_held: int = 0
    realized_r: float = 0.0
    # Running extremes since entry, maintained for the chandelier stop.
    highest_since_entry: float | None = None
    lowest_since_entry: float | None = None
    history: list[tuple[str, float, str]] = field(default_factory=list)

    @property
    def initial_risk(self) -> float:
        return abs(self.entry_price - self.initial)

    def active_stop(self) -> float:
        """The tightest (closest-to-price) stop currently in the stack."""
        candidates = [self.initial]
        for level in (self.breakeven, self.trailing_atr, self.trailing_ema,
                      self.chandelier, self.structure, self.psar):
            if level is not None:
                candidates.append(level)
        return max(candidates) if self.side == "long" else min(candidates)


class StopEngine:
    """Advances stop stacks each bar and signals exits."""

    def __init__(
        self,
        breakeven_at_r: float = 1.0,
        trailing_start_at_r: float = 1.5,
        trailing_atr_multiplier: float = 1.5,
        volatility_exit_threshold: float = 2.0,
        fees_round_trip_pct: float = 0.001,
        chandelier_atr_multiplier: float = 3.0,
    ) -> None:
        self.breakeven_at_r = breakeven_at_r
        self.trailing_start_r = trailing_start_at_r
        self.trailing_atr_mult = trailing_atr_multiplier
        self.vol_exit_th = volatility_exit_threshold
        self.fees_rt = fees_round_trip_pct
        self.chandelier_atr_mult = chandelier_atr_multiplier

    @staticmethod
    def _r_multiple(stack: StopStack, price: float) -> float:
        if stack.initial_risk <= 0:
            return 0.0
        delta = (
            (price - stack.entry_price)
            if stack.side == "long"
            else (stack.entry_price - price)
        )
        return delta / stack.initial_risk

    def update(
        self,
        stack: StopStack,
        current_price: float,
        current_atr: float,
        current_ema_slow: float | None = None,
        rsi_at_extreme_again: bool = False,
        current_high: float | None = None,
        current_low: float | None = None,
        structure_level: float | None = None,
        psar_value: float | None = None,
    ) -> tuple[StopStack, str | None]:
        """Advance the stack one bar. Returns ``(stack, exit_reason)``;
        ``exit_reason`` is ``None`` unless an exit fired.

        ``current_high`` / ``current_low`` feed the chandelier stop's running
        extreme (they default to ``current_price`` if you only have closes).
        ``structure_level`` and ``psar_value`` activate the structure and PSAR
        stops when supplied — each ratchets toward the level, tighten-only."""
        stack.bars_held += 1
        r_now = self._r_multiple(stack, current_price)
        stack.realized_r = max(stack.realized_r, r_now)

        # Volatility spike -> bail.
        if stack.volatility_baseline and current_atr > self.vol_exit_th * stack.volatility_baseline:
            return stack, f"volatility spike ({current_atr / stack.volatility_baseline:.2f}x baseline)"

        # Momentum re-extreme (mean reversion only).
        if stack.rsi_stop and rsi_at_extreme_again:
            return stack, "momentum returned to extreme"

        # Time stop: hasn't reached 1R within the bar limit.
        if (
            stack.time_stop_bars is not None
            and stack.bars_held >= stack.time_stop_bars
            and stack.realized_r < 1.0
        ):
            return stack, f"time stop after {stack.bars_held} bars without 1R"

        # Breakeven at 1R (parked just past entry to clear fees).
        if stack.breakeven is None and r_now >= self.breakeven_at_r:
            fees_buffer = stack.entry_price * self.fees_rt
            be = stack.entry_price + (fees_buffer if stack.side == "long" else -fees_buffer)
            stack.breakeven = be
            stack.history.append(("breakeven_activated", be, "1R reached"))

        # Trailing ATR stop (tighten-only).
        if r_now >= self.trailing_start_r:
            new_trail = (
                current_price - self.trailing_atr_mult * current_atr
                if stack.side == "long"
                else current_price + self.trailing_atr_mult * current_atr
            )
            if stack.trailing_atr is None:
                stack.trailing_atr = new_trail
                stack.history.append(("trail_atr_activated", new_trail, f"{self.trailing_start_r}R reached"))
            elif (stack.side == "long" and new_trail > stack.trailing_atr) or (
                stack.side == "short" and new_trail < stack.trailing_atr
            ):
                stack.trailing_atr = new_trail
                stack.history.append(("trail_atr_tightened", new_trail, "trail"))

        # Trailing EMA stop (tighten-only), for trend trades.
        if current_ema_slow is not None and r_now >= self.trailing_start_r:
            if stack.trailing_ema is None:
                stack.trailing_ema = current_ema_slow
                stack.history.append(("trail_ema_activated", current_ema_slow, ""))
            elif (stack.side == "long" and current_ema_slow > stack.trailing_ema) or (
                stack.side == "short" and current_ema_slow < stack.trailing_ema
            ):
                stack.trailing_ema = current_ema_slow

        # Chandelier stop (tighten-only): trail ATR from the highest high (long) /
        # lowest low (short) *since entry*, not from the current bar.
        if stack.use_chandelier:
            high = current_high if current_high is not None else current_price
            low = current_low if current_low is not None else current_price
            if stack.side == "long":
                stack.highest_since_entry = (
                    high if stack.highest_since_entry is None
                    else max(stack.highest_since_entry, high)
                )
                level = stack.highest_since_entry - self.chandelier_atr_mult * current_atr
                if stack.chandelier is None or level > stack.chandelier:
                    stack.chandelier = level
                    stack.history.append(("chandelier", level, "trail"))
            else:
                stack.lowest_since_entry = (
                    low if stack.lowest_since_entry is None
                    else min(stack.lowest_since_entry, low)
                )
                level = stack.lowest_since_entry + self.chandelier_atr_mult * current_atr
                if stack.chandelier is None or level < stack.chandelier:
                    stack.chandelier = level
                    stack.history.append(("chandelier", level, "trail"))

        # Structure stop (tighten-only): ratchet to a swing level you supply —
        # a swing low for longs, a swing high for shorts. Never loosens.
        if structure_level is not None:
            if stack.structure is None or (
                (stack.side == "long" and structure_level > stack.structure)
                or (stack.side == "short" and structure_level < stack.structure)
            ):
                stack.structure = structure_level
                stack.history.append(("structure", structure_level, "swing"))

        # Parabolic SAR stop (tighten-only): ratchet to a PSAR value you supply.
        # When PSAR flips past price it tightens onto it and triggers the exit.
        if psar_value is not None:
            if stack.psar is None or (
                (stack.side == "long" and psar_value > stack.psar)
                or (stack.side == "short" and psar_value < stack.psar)
            ):
                stack.psar = psar_value
                stack.history.append(("psar", psar_value, ""))

        # Stopped out?
        active = stack.active_stop()
        if stack.side == "long" and current_price <= active:
            return stack, f"stopped out at {active:.4f}"
        if stack.side == "short" and current_price >= active:
            return stack, f"stopped out at {active:.4f}"

        return stack, None
