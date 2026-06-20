# Contributing to riskkit

Thanks for your interest. riskkit aims to be the dependable, framework-agnostic
risk layer for systematic trading — correctness and clarity matter more than
features.

## Dev setup

```bash
git clone https://github.com/HasibDaddy/riskkit
cd riskkit
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Principles (please keep these)

- **No framework lock-in.** The core must not depend on any exchange SDK, data
  provider, or backtesting framework. Heavy optional deps (like pandas) go
  behind an extra and are imported lazily.
- **Every decision is auditable.** New rules should return *why* they fired, not
  just a boolean.
- **Conservative defaults.** Floors, ceilings, and caps bound every knob.
- **Anti-martingale only.** Nothing in this library may increase risk after a
  loss.

## Pull requests

1. Add or update tests — every behaviour change needs a test.
2. Keep the public API documented (docstrings render in the README examples).
3. Run `pytest` locally; CI runs the suite on Python 3.9–3.12.
4. Update `CHANGELOG.md` under an `## [Unreleased]` heading.

## Good first contributions

- Integration examples/adapters for a specific framework (backtesting.py,
  vectorbt, freqtrade).
- A worked notebook walking through one component on real OHLCV data.
- Edge-case tests for the existing modules.

Open an issue to discuss anything larger before you build it.
