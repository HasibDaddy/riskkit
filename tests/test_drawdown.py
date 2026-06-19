"""Tests for riskkit.drawdown.DrawdownManager."""
from datetime import datetime, timedelta, timezone

import pytest

from riskkit import DrawdownManager

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_first_update_sets_peak_and_normal_tier():
    dm = DrawdownManager()
    s = dm.update(10_000, now=T0)
    assert s.tier == 0
    assert s.peak_equity == 10_000
    assert s.size_multiplier == 1.0
    assert not s.halted


@pytest.mark.parametrize(
    "equity, exp_tier, exp_mult",
    [
        (9_600, 1, 0.75),   # 4% dd
        (9_400, 2, 0.5),    # 6% dd
        (9_200, 3, 0.25),   # 8% dd
        (8_800, 4, 0.0),    # 12% dd -> halt
    ],
)
def test_tier_ladder(equity, exp_tier, exp_mult):
    # Disable the weekly-loss guard so we isolate the drawdown tier ladder.
    dm = DrawdownManager(weekly_loss_pause_pct=100.0)
    dm.update(10_000, now=T0)
    s = dm.update(equity, now=T0)
    assert s.tier == exp_tier
    assert s.size_multiplier == exp_mult


def test_halt_above_threshold():
    dm = DrawdownManager()
    dm.update(10_000, now=T0)
    s = dm.update(8_800, now=T0)  # 12% > 10% halt
    assert s.halted
    assert s.size_multiplier == 0.0


def test_tier3_sets_score_and_concurrency_overrides():
    dm = DrawdownManager(weekly_loss_pause_pct=100.0)  # isolate from weekly guard
    dm.update(10_000, now=T0)
    s = dm.update(9_200, now=T0)  # 8% -> tier 3
    assert s.min_score_override == 85
    assert s.max_concurrent_override == 1


def test_recovery_ramp_steps_down_one_tier_at_a_time():
    dm = DrawdownManager(weekly_loss_pause_pct=100.0)  # isolate the recovery ramp
    dm.update(10_000, now=T0)
    deep = dm.update(9_000, now=T0)  # 10% dd -> tier 3
    assert deep.tier == 3

    # Equity nearly fully recovered, but the ramp only allows one step down.
    s1 = dm.update(9_950, now=T0)
    assert s1.tier == 2
    s2 = dm.update(9_960, now=T0)
    assert s2.tier == 1


def test_non_positive_equity_halts():
    dm = DrawdownManager()
    dm.update(10_000, now=T0)
    s = dm.update(0, now=T0)
    assert s.tier == 4
    assert s.halted


def test_weekly_loss_pause_arms_and_clears():
    dm = DrawdownManager()
    dm.update(10_000, now=T0)
    armed = dm.update(9_600, now=T0)  # -4% in the week, > 3% guard
    assert armed.halted
    assert "weekly" in armed.reason.lower()

    # After the 7-day window rolls over, the pause clears.
    later = dm.update(9_600, now=T0 + timedelta(days=8))
    assert not later.halted
