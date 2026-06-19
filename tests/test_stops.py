"""Tests for riskkit.stops.StopEngine."""
import pytest

from riskkit import StopEngine, StopStack


def test_no_exit_when_price_holds():
    eng = StopEngine()
    stack = StopStack(side="long", entry_price=100, initial=98)
    stack, reason = eng.update(stack, current_price=100.5, current_atr=1.0)
    assert reason is None


def test_breakeven_activates_at_1r():
    eng = StopEngine(fees_round_trip_pct=0.001)
    stack = StopStack(side="long", entry_price=100, initial=98)  # risk = 2
    stack, reason = eng.update(stack, current_price=102, current_atr=1.0)  # +1R
    assert reason is None
    assert stack.breakeven == pytest.approx(100.1)  # entry + fee buffer


def test_trailing_atr_then_stop_out():
    eng = StopEngine(trailing_start_at_r=1.5, trailing_atr_multiplier=1.5)
    stack = StopStack(side="long", entry_price=100, initial=98)
    eng.update(stack, current_price=103, current_atr=1.0)  # +1.5R -> trail at 101.5
    assert stack.trailing_atr == pytest.approx(101.5)
    stack, reason = eng.update(stack, current_price=101.0, current_atr=1.0)  # below trail
    assert reason is not None and "stopped out" in reason


def test_time_stop_fires_without_1r():
    eng = StopEngine()
    stack = StopStack(side="long", entry_price=100, initial=98, time_stop_bars=2)
    eng.update(stack, current_price=100.5, current_atr=1.0)          # bar 1
    stack, reason = eng.update(stack, current_price=100.5, current_atr=1.0)  # bar 2
    assert reason is not None and "time stop" in reason


def test_volatility_spike_exit():
    eng = StopEngine(volatility_exit_threshold=2.0)
    stack = StopStack(side="long", entry_price=100, initial=98, volatility_baseline=1.0)
    stack, reason = eng.update(stack, current_price=100.5, current_atr=3.0)  # 3x baseline
    assert reason is not None and "volatility" in reason


def test_short_side_stop_out():
    eng = StopEngine(trailing_start_at_r=1.5, trailing_atr_multiplier=1.5)
    stack = StopStack(side="short", entry_price=100, initial=102)  # risk = 2
    eng.update(stack, current_price=97, current_atr=1.0)  # +1.5R -> trail at 98.5
    assert stack.trailing_atr == pytest.approx(98.5)
    stack, reason = eng.update(stack, current_price=99.0, current_atr=1.0)  # back above trail
    assert reason is not None and "stopped out" in reason
