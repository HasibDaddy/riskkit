"""Tests for riskkit.session.SessionManager."""
from datetime import datetime, timedelta, timezone

from riskkit import SessionManager, TradeRecord

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_trade(ts, pnl=10.0, score=80, size=1.0, duration=60.0):
    return TradeRecord(
        ts_open=ts - timedelta(minutes=duration),
        ts_close=ts,
        pnl=pnl,
        pnl_pct=pnl / 100,
        score=score,
        position_size_units=size,
        duration_minutes=duration,
        side="long",
        symbol="X",
        strategy="s",
    )


def test_daily_trade_cap():
    sm = SessionManager(max_trades_per_day=2)
    sm.record_trade(make_trade(T0), equity_before=10_000)
    sm.record_trade(make_trade(T0 + timedelta(minutes=20)), equity_before=10_000)
    d = sm.can_open("s", now=T0 + timedelta(minutes=40))
    assert not d.allowed and "trade cap" in d.reason


def test_consecutive_loss_cooldown():
    sm = SessionManager()
    sm.record_trade(make_trade(T0, pnl=-5.0), equity_before=10_000)
    sm.record_trade(make_trade(T0 + timedelta(minutes=20), pnl=-5.0), equity_before=10_000)
    # 2 consecutive losses -> 30 min cooldown armed
    d = sm.can_open("s", now=T0 + timedelta(minutes=25))
    assert not d.allowed and "cooldown" in d.reason


def test_tilt_on_weak_signal():
    sm = SessionManager(min_score=65)
    # 2h apart with 60-min holds -> clean gaps, equal hold times, equal sizes.
    for i in range(5):
        sm.recent_trades.append(make_trade(T0 + timedelta(hours=2 * i), score=80))
    assert sm.detect_tilt(100) is False
    sm.recent_trades[-1].score = 50  # one weak signal in the last 5
    assert sm.detect_tilt(100) is True


def test_tilt_on_size_increase_after_loss():
    sm = SessionManager()
    trades = [make_trade(T0 + timedelta(hours=2 * i), pnl=10, size=1.0) for i in range(5)]
    trades[2].pnl = -5.0       # a loss...
    trades[3].position_size_units = 2.0  # ...followed by a bigger position
    sm.recent_trades = trades
    assert sm.detect_tilt(100) is True
