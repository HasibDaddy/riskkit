# Components

Every component is independent — use one or all six.

## PositionSizer

Volatility-adjusted fixed-fractional sizing. You pick a base risk fraction; the
sizer scales it down when volatility is above baseline, applies an optional
half-Kelly ceiling, runs a reduction ladder (losing streaks, drawdown tiers,
daily loss), and enforces a hard notional cap. Returns the units **and** every
multiplier that fired.

## DrawdownManager

Tracks high-water-mark drawdown and maps it onto tiers: normal → 0.75x → 0.5x →
0.25x → halt. A recovery ramp steps the tier back down one level at a time once
equity recovers, and a rolling weekly-loss guard pauses new entries for 24h.

## StopEngine

Each position carries a **stack** of stops — initial, break-even (armed at 1R),
ATR trailing, EMA trailing, time, and volatility. The tightest stop relative to
price is active, and stops only ever move closer. Call `update()` once per bar;
it returns an exit reason or `None`.

## CorrelationGuard

Allows at most one open position per correlation group. Groups can be static
(you define them) or computed dynamically from a rolling return-correlation
matrix (install the `pandas` extra).

## SessionManager

Behavioural guardrails: daily trade/loss caps, profit-taking stops, minimum
spacing between trades, escalating cooldowns after losing streaks, and tilt
detection (shrinking hold times, size-up after losses, rapid-fire entries, weak
signals).

## PreTradeValidator

The composable final gate. Assemble a `TradeProposal` and `validate()` runs every
rule across market quality, sizing, risk limits, signal quality, and timing —
returning a pass/fail line for each and an overall veto.
