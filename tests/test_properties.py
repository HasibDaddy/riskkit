"""Property-based tests for riskkit's core invariants.

These assert the guarantees that make riskkit *risk* management — across thousands
of randomized inputs, not a handful of hand-picked cases:

  1. a position's notional never exceeds the configured cap, and its risk fraction
     never exceeds the ceiling;
  2. size never *increases* after more consecutive losses or deeper drawdown
     (the anti-martingale guarantee);
  3. the per-sector exposure cap is never breached, whatever the fill sequence;
  4. the standalone sizers stay within bounds — vol-targeting never tops its
     notional cap and shrinks as volatility rises; inverse-vol weights sum to 1
     and reward lower vol; Kelly stays in ``[0, fraction]`` and grows with edge.

Skipped automatically when hypothesis isn't installed (it's in the `dev` extra).
"""
import pytest

pytest.importorskip("hypothesis")
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from riskkit import (
    PositionSizer,
    RiskConfig,
    RiskManager,
    SizingInputs,
    TradeIntent,
    inverse_vol_weights,
    kelly_fraction,
    volatility_target_size,
)

equities = st.floats(min_value=100, max_value=1e7, allow_nan=False, allow_infinity=False)
prices = st.floats(min_value=0.01, max_value=1e5, allow_nan=False, allow_infinity=False)
distances = st.floats(min_value=1e-4, max_value=1e4, allow_nan=False, allow_infinity=False)
vols = st.floats(min_value=1e-4, max_value=1e4, allow_nan=False, allow_infinity=False)
scores = st.integers(min_value=0, max_value=100)
losses = st.integers(min_value=0, max_value=20)
drawdowns = st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False)

# v0.4 surface
return_vols = st.floats(min_value=1e-4, max_value=10.0, allow_nan=False, allow_infinity=False)
magnitudes = st.floats(min_value=1e-3, max_value=100.0, allow_nan=False, allow_infinity=False)
probabilities = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
fractions = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
sectors = st.sampled_from(["alpha", "beta", "gamma"])


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


# --------------------------------------------------------- v0.4: portfolio cap

@given(legs=st.lists(st.tuples(sectors, prices, fractions), min_size=1, max_size=25))
@settings(max_examples=200)
def test_sector_exposure_cap_never_breached(legs):
    """However trades arrive, no sector's open notional may exceed the cap."""
    cap = 10.0
    risk = RiskManager(RiskConfig(
        base_risk_pct=1.0,
        max_notional_pct=20.0,
        max_exposure_per_sector_pct=cap,
        # Strip every *other* gate so only the sector cap can block a fill.
        validator=dict(min_score=0, min_rr_ratio=1.0, max_total_exposure_pct=1e9,
                       max_daily_trades=10**9),
        session=dict(min_minutes_between_trades=0, max_trades_per_day=10**9,
                     max_daily_loss_pct=1e9, min_score=0),
    ))
    risk.on_equity(1_000_000.0)
    for i, (sector, entry, stop_frac) in enumerate(legs):
        stop = entry * (0.5 + 0.49 * stop_frac)      # stop strictly below entry
        decision = risk.evaluate(TradeIntent(
            symbol=f"S{i}", side="long", sector=sector,
            entry_price=entry, stop_price=stop,
            target_price=entry + 3 * (entry - stop), score=100,
        ))
        if decision.ok:
            risk.on_fill(decision)
        # Invariant must hold after *every* step, not just at the end.
        assert all(pct <= cap + 1e-6 for pct in risk.sector_exposure().values())


# ------------------------------------------------------- v0.4: standalone sizers

@given(vols=st.dictionaries(st.text(min_size=1, max_size=4), return_vols,
                            min_size=1, max_size=12))
@settings(max_examples=300)
def test_inverse_vol_weights_normalize_and_reward_low_vol(vols):
    w = inverse_vol_weights(vols)
    assert w.keys() == vols.keys()                       # all positive vols kept
    assert sum(w.values()) == pytest.approx(1.0)
    assert all(0 < x <= 1 + 1e-9 for x in w.values())
    for a in vols:
        for b in vols:
            if vols[a] <= vols[b]:
                assert w[a] >= w[b] - 1e-9               # lower vol -> >= weight


@given(equity=equities, price=prices, vol=return_vols,
       target=st.floats(min_value=1e-3, max_value=50.0, allow_nan=False, allow_infinity=False),
       cap=st.floats(min_value=1.0, max_value=200.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=300)
def test_vol_target_size_never_exceeds_notional_cap(equity, price, vol, target, cap):
    units = volatility_target_size(equity, price, vol, target, max_notional_pct=cap)
    assert units >= 0
    assert units * price <= equity * cap / 100.0 * (1 + 1e-9) + 1e-6


@given(equity=equities, price=prices,
       target=st.floats(min_value=1e-3, max_value=50.0, allow_nan=False, allow_infinity=False),
       v1=return_vols, v2=return_vols)
@settings(max_examples=300)
def test_vol_target_size_non_increasing_in_volatility(equity, price, target, v1, v2):
    assume(v1 <= v2)
    u1 = volatility_target_size(equity, price, v1, target)
    u2 = volatility_target_size(equity, price, v2, target)
    assert u2 <= u1 + 1e-9                                # more vol -> never larger


@given(p=probabilities, win=magnitudes, loss=magnitudes, frac=fractions)
@settings(max_examples=300)
def test_kelly_fraction_bounded(p, win, loss, frac):
    # kelly ≤ 1, so kelly·fraction is always within [0, fraction].
    assert 0.0 <= kelly_fraction(p, win, loss, fraction=frac) <= frac + 1e-9


@given(p1=probabilities, p2=probabilities, win=magnitudes, loss=magnitudes)
@settings(max_examples=300)
def test_kelly_fraction_increases_with_edge(p1, p2, win, loss):
    assume(p1 <= p2)
    assert kelly_fraction(p1, win, loss) <= kelly_fraction(p2, win, loss) + 1e-9
