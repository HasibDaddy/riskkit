# riskkit roadmap

**The vision:** riskkit should become the default, framework-agnostic **risk
layer** for systematic trading in Python — the dependable answer to *"how much do
I trade, when do I cut size, and when do I stop?"*, usable from any backtester or
live bot. Backtesters handle signals and execution; riskkit handles survival.

The six core components — position sizing, drawdown control, stops, correlation
limits, session/tilt guards, and a pre-trade validator — landed in **v0.2**. From
here the focus is making them effortless to adopt and deeper where it counts.

## v0.3 — Adoption & ergonomics

- **`RiskManager` façade** ✅ *shipped* — wires all six components from a single
  config; one `evaluate()` call sizes + validates a trade:
  ```python
  from riskkit import RiskManager, RiskConfig, TradeIntent

  risk = RiskManager(RiskConfig(
      base_risk_pct=1.0, max_notional_pct=4.0,
      drawdown=dict(tier1_pct=3, halt_pct=10),
      session=dict(max_trades_per_day=5),
  ))
  risk.on_equity(equity)                       # refresh drawdown/session state
  decision = risk.evaluate(TradeIntent(...))   # size + validate in one call
  if decision.ok:
      place(decision.units, decision.stop)
  ```
- **First-class framework adapters:**
  - backtesting.py ✅ *shipped* — the `RiskkitStrategy` mixin auto-sizes and
    validates entries via `RiskManager` (`riskkit.adapters.backtesting`).
  - freqtrade — a ready strategy mixin / documented callbacks.
  - vectorbt — helpers to apply sizing & drawdown control to vectorized signals.
- **Config presets** ✅ *shipped* — `RiskConfig.conservative()` / `.balanced()` /
  `.aggressive()` (and `RiskConfig.preset(name)`); load from a dict
  (`from_dict`) or a YAML file (`from_yaml`).

## v0.4 — Depth & correctness

- More sizers: volatility targeting, equal-risk, ATR-based, full/fractional Kelly.
- More stops: chandelier, parabolic SAR, structure-based.
- Portfolio-level risk: total open "heat", sector / asset-class caps, simple VaR/CVaR.
- Property-based tests (hypothesis) for the core invariants:
  *never increase risk after a loss; never exceed configured caps.*

## v0.5 — Observability & docs

- A decision / audit-trail object with optional CSV / pandas export.
- Deployed docs site with recipes and a short "risk 101" guide.
- Benchmark notebooks quantifying riskkit's effect (e.g. drawdown reduction) on
  real strategies.

## v1.0 — Stability

- Frozen, semver-committed public API.
- Published to PyPI under a clean distribution name.
- A small cookbook of example repos.

Feedback and contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md)
and open an issue.
