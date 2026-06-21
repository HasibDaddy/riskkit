"""Property-based tests for riskkit's core invariants.

These assert the guarantees that make riskkit *risk* management — across thousands
of randomized inputs, not a handful of hand-picked cases:

  1. a position's notional never exceeds the configured cap, and its risk fraction
     never exceeds the ceiling;
  2. size never *increases* after more consecutive losses or deeper drawdown
     (the anti-martingale guarantee).

Skipped automatically when hypothesis isn't installed (it's in the `dev` extra).
"""
import pytest

pytest.importorskip("hypothesis")
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from riskkit import PositionSizer, SizingInputs

equities = st.floats(min_value=100, max_value=1e7, allow_nan=False, allow_infinity=False)
prices = st.floats(min_value=0.01, max_value=1e5, allow_nan=False, allow_infinity=False)
distances = st.floats(min_value=1e-4, max_value=1e4, allow_nan=False, allow_infinity=False)
vols = st.floats(min_value=1e-4, max_value=1e4, allow_nan=False, allow_infinity=False)
scores = st.integers(min_value=0, max_value=100)
losses = st.integers(min_value=0, max_value=20)
drawdowns = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)


@given(equity=equities, entry=prices, dist=distances, atr=vols, base=vols, score=scores)
@settings(max_examples=300)
def test_notional_and_risk_never_exceed_caps(equity, entry, dist, atr, base, score):
    sizer = PositionSizer(base_risk_pct=1.0, max_risk_pct=1.5, max_notional_pct=4.0)
    r = sizer.size(SizingInputs(
        equity=equity, entry_price=entry, stop_price=entry + dist,
        atr=atr, atr_baseline=base, confluence_score=score,
    ))
    # Notional cap is absolute; risk fraction never tops the ceiling.
    assert r.notional <= equity * 0.04 * (1 + 1e-9) + 1e-6
    assert r.risk_pct <= 0.015 + 1e-9
    assert r.units >= 0


@given(equity=equities, entry=prices, dist=distances, a=losses, b=losses)
@settings(max_examples=300)
def test_more_losses_never_increase_size(equity, entry, dist, a, b):
    assume(a <= b)
    sizer = PositionSizer()

    def units(consecutive_losses):
        return sizer.size(SizingInputs(
            equity=equity, entry_price=entry, stop_price=entry + dist,
            atr=1.0, atr_baseline=1.0, consecutive_losses=consecutive_losses,
        )).units

    assert units(b) <= units(a) + 1e-9          # more losses -> never larger


@given(equity=equities, entry=prices, dist=distances, a=drawdowns, b=drawdowns)
@settings(max_examples=300)
def test_deeper_drawdown_never_increases_size(equity, entry, dist, a, b):
    assume(a <= b)
    sizer = PositionSizer()

    def units(drawdown_pct):
        return sizer.size(SizingInputs(
            equity=equity, entry_price=entry, stop_price=entry + dist,
            atr=1.0, atr_baseline=1.0, drawdown_pct=drawdown_pct,
        )).units

    assert units(b) <= units(a) + 1e-9          # deeper drawdown -> never larger
