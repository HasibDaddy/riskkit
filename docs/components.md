# Components

Every component is independent — use one or all six. When you want all of them
working together, reach for the `RiskManager` façade rather than wiring them up
yourself.

## RiskManager

The façade over the other six. Build it from a single `RiskConfig` (which carries
two promoted knobs — `base_risk_pct`, `max_notional_pct` — plus a pass-through
dict of keyword arguments for each component), then:

- `on_equity(equity)` — refresh drawdown and session state as the account moves.
- `evaluate(TradeIntent(...))` — size **and** validate one trade, returning a
  `RiskDecision` (`ok`, `units`, `stop`, `risk_pct`, and `reasons` listing every
  gate that vetoed it, plus the full component results for auditing).
- `on_fill(decision)` / `on_close(trade)` — keep the open book and the session's
  streak/cooldown state current.

`decision.ok` is the AND of the pre-trade validator passing *and* the session
manager permitting an entry — the latter catches behavioural blocks (tilt,
cooldowns, profit target hit) that have no dedicated validator flag. The
underlying components are exposed as attributes (`.sizer`, `.drawdown`, `.stops`,
`.correlation`, `.session`, `.validator`) when you need to reach past the façade.

Because the manager tracks the open book, it enforces portfolio-level caps as you
trade: total open **notional** (`max_notional_pct` extended across positions),
total open **heat** — the capital actually at risk if every stop is hit
(`max_portfolio_heat_pct`, off by default), and per-sector / asset-class
**concentration** (`max_exposure_per_sector_pct`, off by default) so no single
sector can dominate the book. Tag a trade's sector with `TradeIntent(sector=...)`;
untagged trades are never sector-capped. Read any of these live with
`exposure_pct()` / `portfolio_heat_pct()` / `sector_exposure_pct(sector)` (or
`sector_exposure()` for the full per-sector breakdown).

## PositionSizer

Volatility-adjusted fixed-fractional sizing. You pick a base risk fraction; the
sizer scales it down when volatility is above baseline, applies an optional
half-Kelly ceiling, runs a reduction ladder (losing streaks, drawdown tiers,
daily loss), and enforces a hard notional cap. Returns the units **and** every
multiplier that fired.

When the stop-distance model isn't what you want, three standalone sizing helpers
stand on their own (pure functions, no dependencies):

- `kelly_fraction(win_rate, avg_win, avg_loss, fraction=1.0)` — the edge-optimal
  risk fraction; pass `fraction=0.5` for half-Kelly. Clamps to 0 with no edge.
- `volatility_target_size(equity, price, return_volatility, target_volatility_pct,
  max_notional_pct=100)` — units sized so a position's expected volatility hits a
  target % of equity (calmer instrument → larger position), capped by notional.
- `inverse_vol_weights({symbol: volatility})` — naive risk-parity weights (∝ 1/σ)
  that sum to 1.0, so every position contributes equal risk.

## DrawdownManager

Tracks high-water-mark drawdown and maps it onto tiers: normal → 0.75x → 0.5x →
0.25x → halt. A recovery ramp steps the tier back down one level at a time once
equity recovers, and a rolling weekly-loss guard pauses new entries for 24h.

## StopEngine

Each position carries a **stack** of stops — initial, break-even (armed at 1R),
ATR trailing, EMA trailing, chandelier (ATR from the highest high / lowest low
since entry), structure (ratchets to a swing level you pass), PSAR (ratchets to a
Parabolic SAR value you pass), time, and volatility. The tightest stop relative to
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

## Metrics

Standalone risk metrics over a return series: `value_at_risk(returns, confidence)`
and `conditional_value_at_risk(returns, confidence)` (historical VaR and expected
shortfall), both reported as positive loss magnitudes. Pure standard library.
