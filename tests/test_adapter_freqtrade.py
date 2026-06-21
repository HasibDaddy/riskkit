"""Tests for the freqtrade adapter — framework-agnostic, so no freqtrade needed."""
from datetime import datetime, timedelta, timezone

import pytest

from riskkit import RiskConfig
from riskkit.adapters.freqtrade import FreqtradeRiskManager

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _frm(**cfg):
    return FreqtradeRiskManager(RiskConfig(**cfg) if cfg else None)


def test_stake_amount_returns_notional_when_ok():
    frm = _frm(base_risk_pct=1.0, max_notional_pct=4.0)
    stake = frm.stake_amount(pair="BTC/USDT", equity=10_000, current_rate=100,
                             stop_price=98, target_price=104, max_stake=1e9,
                             score=80, now=T0)
    assert stake == pytest.approx(400.0)              # 4% notional cap on 10k
    assert frm.confirm_entry("BTC/USDT") is True


def test_stake_clamped_to_max_stake():
    frm = _frm(max_notional_pct=15.0)
    stake = frm.stake_amount(pair="BTC/USDT", equity=10_000, current_rate=100,
                             stop_price=98, target_price=106, max_stake=250.0,
                             score=80, now=T0)
    assert stake == pytest.approx(250.0)              # clamped below riskkit notional


def test_veto_returns_zero_and_confirm_false():
    frm = _frm()
    stake = frm.stake_amount(pair="BTC/USDT", equity=10_000, current_rate=100,
                             stop_price=98, target_price=104, max_stake=1e9,
                             score=10, now=T0)        # score below the floor
    assert stake == 0.0
    assert frm.confirm_entry("BTC/USDT") is False
    assert any("score" in r for r in frm.last_decision("BTC/USDT").reasons)


def test_below_min_stake_skips():
    frm = _frm(max_notional_pct=4.0)
    stake = frm.stake_amount(pair="BTC/USDT", equity=10_000, current_rate=100,
                             stop_price=98, target_price=104, max_stake=1e9,
                             min_stake=500.0, score=80, now=T0)   # 400 < 500
    assert stake == 0.0


def test_optional_target_keeps_rr_gate_neutral():
    # No target supplied → a target meeting exactly the min R:R is assumed.
    frm = _frm()
    stake = frm.stake_amount(pair="BTC/USDT", equity=10_000, current_rate=100,
                             stop_price=98, max_stake=1e9, score=80, now=T0)
    assert stake > 0
    assert all("rr_ratio" not in r for r in frm.last_decision("BTC/USDT").reasons)


def test_correlation_blocks_second_pair_after_fill():
    frm = _frm(correlation=dict(static_groups={"majors": {"BTC/USDT", "ETH/USDT"}}))
    s1 = frm.stake_amount(pair="BTC/USDT", equity=10_000, current_rate=100,
                          stop_price=98, target_price=104, max_stake=1e9, score=80, now=T0)
    assert s1 > 0
    frm.on_fill("BTC/USDT")
    s2 = frm.stake_amount(pair="ETH/USDT", equity=10_000, current_rate=50,
                          stop_price=49, target_price=52, max_stake=1e9, score=80, now=T0)
    assert s2 == 0.0
    assert any("correlation" in r for r in frm.last_decision("ETH/USDT").reasons)


def test_on_exit_feeds_session():
    frm = _frm()
    frm.on_exit(pair="BTC/USDT", pnl=50.0, pnl_pct=0.5,
                open_time=T0, close_time=T0 + timedelta(hours=1),
                amount=4.0, equity_before=10_000)
    assert frm.risk.session.day_trades == 1
