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


# Push the ATR-trail / breakeven activation out of the way so each new stop is
# the only level driving the exit.
def _isolated_engine(**kw):
    return StopEngine(trailing_start_at_r=100, breakeven_at_r=100, **kw)


def test_chandelier_anchors_to_running_high_and_stops_out():
    eng = _isolated_engine(chandelier_atr_multiplier=3.0)
    stack = StopStack(side="long", entry_price=100, initial=98, use_chandelier=True)
    eng.update(stack, current_price=110, current_atr=1.0, current_high=110)
    assert stack.chandelier == pytest.approx(107.0)              # 110 high - 3*ATR
    # Price drifts down but the high (110) holds → chandelier stays 107.
    _, reason = eng.update(stack, current_price=108, current_atr=1.0, current_high=108)
    assert reason is None
    _, reason = eng.update(stack, current_price=106, current_atr=1.0, current_high=106)
    assert reason is not None and "stopped out" in reason        # 106 <= 107


def test_chandelier_ratchets_up_on_new_highs():
    eng = _isolated_engine(chandelier_atr_multiplier=3.0)
    stack = StopStack(side="long", entry_price=100, initial=98, use_chandelier=True)
    eng.update(stack, current_price=110, current_atr=1.0, current_high=110)
    eng.update(stack, current_price=115, current_atr=1.0, current_high=115)
    assert stack.chandelier == pytest.approx(112.0)              # tightened to 115 - 3


def test_chandelier_short_side():
    eng = _isolated_engine(chandelier_atr_multiplier=3.0)
    stack = StopStack(side="short", entry_price=100, initial=102, use_chandelier=True)
    eng.update(stack, current_price=90, current_atr=1.0, current_low=90)
    assert stack.chandelier == pytest.approx(93.0)               # 90 low + 3*ATR
    _, reason = eng.update(stack, current_price=94, current_atr=1.0, current_low=90)
    assert reason is not None and "stopped out" in reason        # 94 >= 93


def test_structure_stop_ratchets_and_never_loosens():
    eng = _isolated_engine()
    stack = StopStack(side="long", entry_price=100, initial=98)
    eng.update(stack, current_price=105, current_atr=1.0, structure_level=101)
    assert stack.structure == pytest.approx(101.0)
    eng.update(stack, current_price=105, current_atr=1.0, structure_level=103)
    assert stack.structure == pytest.approx(103.0)              # ratchets up
    eng.update(stack, current_price=105, current_atr=1.0, structure_level=99)
    assert stack.structure == pytest.approx(103.0)              # lower swing ignored
    _, reason = eng.update(stack, current_price=102, current_atr=1.0)
    assert reason is not None and "stopped out" in reason        # 102 <= 103


def test_psar_flip_past_price_triggers_exit():
    eng = _isolated_engine()
    stack = StopStack(side="long", entry_price=100, initial=98)
    eng.update(stack, current_price=105, current_atr=1.0, psar_value=101)
    assert stack.psar == pytest.approx(101.0)
    # PSAR flips above price → tightens onto it and triggers the exit.
    _, reason = eng.update(stack, current_price=106, current_atr=1.0, psar_value=107)
    assert stack.psar == pytest.approx(107.0)
    assert reason is not None and "stopped out" in reason        # 106 <= 107


def test_new_stops_inactive_by_default():
    eng = StopEngine()
    stack = StopStack(side="long", entry_price=100, initial=98)
    eng.update(stack, current_price=105, current_atr=1.0)        # profitable, no new-stop inputs
    assert stack.chandelier is None
    assert stack.structure is None
    assert stack.psar is None
