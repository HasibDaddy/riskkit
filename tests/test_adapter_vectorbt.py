"""Tests for the vectorbt sizing helper — pure Python, so no vectorbt needed."""
import pytest

from riskkit import PositionSizer
from riskkit.adapters.vectorbt import size_signals


def test_sizes_only_entry_bars():
    nan = float("nan")
    entries = [nan, 100.0, nan, 100.0]
    stops = [99.0, 98.0, 99.0, 98.0]
    sizes = size_signals(equity=10_000, entry_prices=entries, stop_prices=stops)
    assert sizes[0] == 0.0 and sizes[2] == 0.0        # no entry on NaN bars
    assert sizes[1] > 0 and sizes[3] > 0


def test_fraction_matches_notional_over_equity():
    sizer = PositionSizer(base_risk_pct=1.0, max_notional_pct=4.0)
    sizes = size_signals(equity=10_000, entry_prices=[100.0], stop_prices=[98.0],
                         sizer=sizer, return_fraction=True)
    assert sizes[0] == pytest.approx(0.04)            # 4% notional cap


def test_return_units():
    sizer = PositionSizer(base_risk_pct=1.0, max_notional_pct=4.0)
    sizes = size_signals(equity=10_000, entry_prices=[100.0], stop_prices=[98.0],
                         sizer=sizer, return_fraction=False)
    assert sizes[0] == pytest.approx(4.0)             # 4 units


def test_drawdown_pct_reduces_size():
    base = size_signals(equity=10_000, entry_prices=[100.0], stop_prices=[90.0],
                        return_fraction=False)[0]
    reduced = size_signals(equity=10_000, entry_prices=[100.0], stop_prices=[90.0],
                           drawdown_pct=[8.0], return_fraction=False)[0]
    assert reduced < base                             # >7% dd → 0.25x ladder


def test_length_mismatch_raises():
    with pytest.raises(ValueError, match="length"):
        size_signals(equity=10_000, entry_prices=[100.0, 100.0], stop_prices=[98.0])


def test_scalar_and_sequence_inputs_agree():
    s_scalar = size_signals(equity=10_000, entry_prices=[100.0], stop_prices=[98.0],
                            atr=2.0, atr_baseline=2.0, return_fraction=False)
    s_seq = size_signals(equity=[10_000], entry_prices=[100.0], stop_prices=[98.0],
                         atr=[2.0], atr_baseline=[2.0], return_fraction=False)
    assert s_scalar == s_seq
