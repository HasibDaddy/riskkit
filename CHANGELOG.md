# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

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
