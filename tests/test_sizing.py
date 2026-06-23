"""Tests for riskkit.sizing.PositionSizer."""
import pytest

from riskkit import (
    PositionSizer,
    SizingInputs,
    inverse_vol_weights,
    kelly_fraction,
    volatility_target_size,
)


def base_inputs(**overrides):
    """Inputs where the notional cap does not bind (stop is far from entry)."""
    defaults = dict(
        equity=10_000.0,
        entry_price=100.0,
        stop_price=50.0,   # risk_per_unit = 50 -> risk-based units stay small
        atr=2.0,
        atr_baseline=2.0,
        confluence_score=80,  # below high-conviction, above the 70-74 penalty band
    )
    defaults.update(overrides)
    return SizingInputs(**defaults)


def test_normal_size_uses_base_risk():
    sizer = PositionSizer()  # base 1%, max_notional 4%
    r = sizer.size(base_inputs())
    # 1% of 10k = $100 risk / $50 per unit = 2 units.
    assert r.units == pytest.approx(2.0)
    assert r.risk_pct == pytest.approx(0.01)
    assert r.notional == pytest.approx(200.0)
    assert r.reason_for_zero is None
    assert "notional_cap" not in r.multipliers_applied


def test_high_conviction_increases_size():
    sizer = PositionSizer()
    r = sizer.size(base_inputs(confluence_score=90))  # >= 85 -> 1.5x, capped at max_risk
    assert "high_conviction" in r.multipliers_applied
    assert r.units == pytest.approx(3.0)  # risk hits the 1.5% ceiling


def test_reduction_ladder_after_losses():
    sizer = PositionSizer()
    r = sizer.size(base_inputs(consecutive_losses=3))  # 0.5x
    assert r.multipliers_applied["consecutive_losses>=3"] == 0.5
    assert r.units == pytest.approx(1.0)


def test_risk_below_floor_skips_trade():
    sizer = PositionSizer()
    r = sizer.size(base_inputs(
        consecutive_losses=3,   # 0.5
        drawdown_pct=8.0,       # 0.25
        daily_loss_pct=2.0,     # 0.5  -> 1% * 0.0625 = 0.0625% < 0.25% floor
    ))
    assert r.units == 0
    assert r.reason_for_zero is not None and "floor" in r.reason_for_zero


def test_zero_distance_stop_skips_trade():
    sizer = PositionSizer()
    r = sizer.size(base_inputs(stop_price=100.0))
    assert r.units == 0
    assert "zero-distance" in r.reason_for_zero


def test_notional_cap_binds_when_stop_is_tight():
    sizer = PositionSizer()
    # Tight stop -> risk math wants more units than the 4% notional cap allows.
    r = sizer.size(base_inputs(stop_price=99.0, confluence_score=80))
    assert "notional_cap" in r.multipliers_applied
    assert r.notional == pytest.approx(400.0)  # exactly 4% of 10k equity
    # When the cap binds, risk_pct reflects realized risk, not the 1% target.
    assert r.risk_pct == pytest.approx(r.risk_amount / 10_000)
    assert r.risk_pct < 0.01


def test_higher_volatility_reduces_size():
    sizer = PositionSizer()
    calm = sizer.size(base_inputs(atr=2.0, atr_baseline=2.0))
    choppy = sizer.size(base_inputs(atr=4.0, atr_baseline=2.0))  # ratio 2 -> half risk
    assert choppy.units < calm.units
    assert choppy.risk_pct == pytest.approx(calm.risk_pct / 2)


def test_kelly_ceiling_skips_when_no_edge():
    sizer = PositionSizer()
    r = sizer.size(base_inputs(win_rate=0.5, avg_win=1.0, avg_loss=1.0))  # kelly = 0
    assert r.units == 0


def test_kelly_with_edge_allows_trade():
    sizer = PositionSizer()
    r = sizer.size(base_inputs(win_rate=0.6, avg_win=2.0, avg_loss=1.0))  # half-kelly = 20%
    assert r.units > 0


# ----------------------------------------------------- standalone sizers


def test_kelly_fraction_edge_and_fraction():
    # win 0.6, 2:1 payoff → kelly = 0.6 − 0.4/2 = 0.4 (full); half = 0.2.
    assert kelly_fraction(0.6, 2.0, 1.0) == pytest.approx(0.4)
    assert kelly_fraction(0.6, 2.0, 1.0, fraction=0.5) == pytest.approx(0.2)


def test_kelly_fraction_no_or_negative_edge_is_zero():
    assert kelly_fraction(0.5, 1.0, 1.0) == 0.0      # break-even → 0
    assert kelly_fraction(0.4, 1.0, 1.0) == 0.0      # negative edge clamps to 0
    # Degenerate inputs (any of the three ≤ 0) → 0.
    assert kelly_fraction(0.0, 1.0, 1.0) == 0.0
    assert kelly_fraction(0.6, 0.0, 1.0) == 0.0
    assert kelly_fraction(0.6, 1.0, 0.0) == 0.0


def test_volatility_target_size_hits_target_and_scales_inversely():
    # target 1% of 10k = $100 vol; per-unit vol = 0.02 × 100 = $2 → 50 units.
    assert volatility_target_size(10_000, 100, 0.02, 1.0) == pytest.approx(50.0)
    # Half the volatility → double the size (same risk budget).
    assert volatility_target_size(10_000, 100, 0.01, 1.0) == pytest.approx(100.0)


def test_volatility_target_size_respects_notional_cap():
    # Unbounded this would be 250 units (250% notional); capped to 100% = 100 units.
    assert volatility_target_size(10_000, 100, 0.02, 5.0) == pytest.approx(100.0)
    # Raising the cap lets the full vol-target size through.
    assert volatility_target_size(10_000, 100, 0.02, 5.0, max_notional_pct=300) == pytest.approx(250.0)


@pytest.mark.parametrize("bad", [
    dict(equity=0, price=100, return_volatility=0.02, target_volatility_pct=1.0),
    dict(equity=10_000, price=0, return_volatility=0.02, target_volatility_pct=1.0),
    dict(equity=10_000, price=100, return_volatility=0.0, target_volatility_pct=1.0),
    dict(equity=10_000, price=100, return_volatility=0.02, target_volatility_pct=0.0),
])
def test_volatility_target_size_degenerate_inputs_zero(bad):
    assert volatility_target_size(**bad) == 0.0


def test_inverse_vol_weights_are_risk_parity():
    w = inverse_vol_weights({"A": 0.10, "B": 0.20})
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["A"] == pytest.approx(2 / 3)   # half the vol of B → twice the weight
    assert w["B"] == pytest.approx(1 / 3)
    # Equal vols → equal weights.
    assert inverse_vol_weights({"A": 0.1, "B": 0.1}) == pytest.approx({"A": 0.5, "B": 0.5})


def test_inverse_vol_weights_drops_nonpositive_and_handles_empty():
    assert inverse_vol_weights({"A": 0.1, "B": 0.0, "C": -0.2}) == {"A": 1.0}
    assert inverse_vol_weights({}) == {}
    assert inverse_vol_weights({"A": 0.0}) == {}
