# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Runnable integration examples for backtesting.py and freqtrade.
- mkdocs documentation site (Home / Quickstart / Components / Integrations).
- PyPI trusted-publishing release workflow and `PUBLISHING.md` guide.

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
