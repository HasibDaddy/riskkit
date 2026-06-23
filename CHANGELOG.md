# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Standalone, composable **sizers** (pure functions): `kelly_fraction()` (edge-optimal
  risk fraction, `fraction=0.5` for half-Kelly), `volatility_target_size()` (size a
  position to a target volatility, notional-capped), and `inverse_vol_weights()` (naive
  risk-parity weights ∝ 1/σ). `PositionSizer` now delegates its half-Kelly ceiling to
  `kelly_fraction` (single source of truth).
- Portfolio-level **heat** cap — `RiskConfig(max_portfolio_heat_pct=...)` limits the
  total capital at risk across open positions (Σ units × distance-to-stop), checked
  by the validator and surfaced via `RiskManager.portfolio_heat_pct()`. Off by
  default; the presets set it (conservative 4% / balanced 8% / aggressive 15%).
- Per-sector / asset-class **exposure** cap — `RiskConfig(max_exposure_per_sector_pct=...)`
  keeps any one sector from dominating the book. Tag trades with `TradeIntent(sector=...)`;
  the manager tracks open notional per sector (`RiskManager.sector_exposure_pct(sector)`
  and `.sector_exposure()`) and the validator blocks an entry that would push its sector
  over the cap. Untagged trades are never capped. Off by default; the presets set it
  (conservative 4% / balanced 10% / aggressive 25%).
- Property-based tests (hypothesis) for the core invariants: a position never
  exceeds its notional/risk caps, size never increases after losses or deeper
  drawdown (anti-martingale), the per-sector exposure cap is never breached across
  random fill sequences, and the standalone sizers stay within bounds (vol-target
  ≤ notional cap and falls as vol rises; inverse-vol weights sum to 1; Kelly within
  `[0, fraction]` and rising with edge).
- `value_at_risk` / `conditional_value_at_risk` — historical VaR and expected
  shortfall over a return series (positive loss magnitudes; CVaR ≥ VaR by
  construction).

## [0.3.0] - 2026-06-22

### Added
- `RiskManager` façade — wires all six components from a single `RiskConfig` and
  turns one `TradeIntent` into a sized, validated `RiskDecision` in a single
  `evaluate()` call. Tracks drawdown, session, and open-book state for you via
  `on_equity()` / `on_fill()` / `on_close()`. See `examples/risk_manager.py`.
- backtesting.py adapter — `riskkit.adapters.backtesting.RiskkitStrategy`, a
  `Strategy` mixin whose `risk_long()` / `risk_short()` size and validate every
  entry through a `RiskManager` and feed closed trades back to the session. New
  `backtesting` optional extra; see `examples/backtesting_riskmanager.py`.
- `RiskConfig` presets (`conservative` / `balanced` / `aggressive`, plus
  `RiskConfig.preset(name)`) and loaders — `RiskConfig.from_dict()`,
  `RiskConfig.to_dict()`, and `RiskConfig.from_yaml()` (new `yaml` extra).
- freqtrade adapter — `riskkit.adapters.freqtrade.FreqtradeRiskManager`, which
  drives `custom_stake_amount` / `confirm_trade_entry` from a `RiskManager`
  (framework-agnostic: it imports nothing from freqtrade).
- vectorbt adapter — `riskkit.adapters.vectorbt.size_signals`, which sizes an
  array of entry signals with riskkit for `Portfolio.from_signals`.
- Runnable integration examples for backtesting.py and freqtrade.
- mkdocs documentation site (Home / Quickstart / Components / Integrations).
- PyPI trusted-publishing release workflow and `PUBLISHING.md` guide.

### Fixed
- `PositionSizer` now reports `risk_pct` consistent with `risk_amount` when the
  notional cap binds (previously `risk_pct` kept the pre-cap target while
  `risk_amount` reflected the smaller, capped position).

## [0.2.0] - 2026-06-19

### Added
- `StopEngine` / `StopStack` — composable per-position stop stack (initial,
  break-even, ATR-trailing, EMA-trailing, time, and volatility stops); tightest
  stop wins and stops only ever move closer.
- `CorrelationGuard` — one open position per correlation group, from static
  groups and/or a dynamically computed return-correlation matrix (pandas extra).
- `SessionManager` — daily trade/loss caps, profit-taking stops, minimum
  spacing, escalating cooldowns, and tilt detection.
- `PreTradeValidator` — composable final-gate checklist across market quality,
  sizing, risk limits, signal quality, and timing; returns a result per check.
- `examples/pipeline.py` end-to-end demo, contribution guide, and issue/PR
  templates.

### Changed
- Generalized the API to be framework-agnostic (e.g. `symbol`/`score` instead of
  exchange-specific names; correlation groups and regime maps are now injected
  rather than hardcoded).

## [0.1.0] - 2026-06-19

Initial release.

### Added
- `PositionSizer` — volatility-adjusted fixed-fractional position sizing with a
  half-Kelly ceiling, a reduction ladder (losing streaks, drawdown tiers, daily
  loss), a high-conviction bonus, and a hard notional cap. Every adjustment is
  returned for auditing.
- `DrawdownManager` — high-water-mark drawdown tracking with a 5-tier ladder, a
  one-step-at-a-time recovery ramp, and a rolling weekly-loss pause.
- Full type hints (`py.typed`) and a test suite covering both modules.
