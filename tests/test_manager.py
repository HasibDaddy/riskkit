"""Tests for riskkit.manager.RiskManager — the wiring of all six components."""
from datetime import datetime, timedelta, timezone

import pytest

from riskkit import RiskConfig, RiskManager, TradeIntent, TradeRecord

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def clean_intent(**overrides):
    """An intent that clears every gate under the default config."""
    defaults = dict(
        symbol="BTC/USDT", side="long",
        entry_price=100.0, stop_price=98.0, target_price=104.0,  # R:R = 2.0
        score=80, strategy="s",
        atr=2.0, atr_baseline=2.0,
        orderbook_depth=1_000_000.0,
    )
    defaults.update(overrides)
    return TradeIntent(**defaults)


def trade_record(pnl, symbol="BTC/USDT", ts=T0, strategy="s"):
    return TradeRecord(
        ts_open=ts, ts_close=ts, pnl=pnl, pnl_pct=pnl / 100.0,
        score=80, position_size_units=1.0, duration_minutes=60.0,
        side="long", symbol=symbol, strategy=strategy,
    )


# --------------------------------------------------------------------- basics


def test_clean_intent_passes():
    rm = RiskManager()
    rm.on_equity(10_000, now=T0)
    d = rm.evaluate(clean_intent(), now=T0)
    assert d.ok
    assert bool(d) is True
    assert d.units == pytest.approx(4.0)          # capped at 4% notional
    assert d.notional == pytest.approx(400.0)
    assert d.stop == 98.0
    assert d.reasons == []
    # risk_pct and risk_amount agree (both reflect realized, post-cap risk).
    assert d.risk_pct == pytest.approx(d.risk_amount / 10_000)


def test_evaluate_requires_on_equity_first():
    rm = RiskManager()
    with pytest.raises(RuntimeError):
        rm.evaluate(clean_intent(), now=T0)


def test_config_wires_components():
    rm = RiskManager(RiskConfig(
        base_risk_pct=0.5, max_notional_pct=3.0, max_concurrent=2,
        session=dict(max_trades_per_day=2),
        drawdown=dict(tier1_pct=2.0),
        correlation=dict(static_groups={"g": {"X", "Y"}}),
    ))
    assert rm.sizer.base_risk == pytest.approx(0.005)
    assert rm.sizer.max_notional == pytest.approx(0.03)
    assert rm.validator.max_notional_pct == 3.0    # promoted knob reaches validator
    assert rm.session.max_trades == 2
    assert rm.drawdown.tier1 == 2.0
    assert rm.correlation.static_groups == {"g": {"X", "Y"}}


# --------------------------------------------------------------------- drawdown


def test_drawdown_halt_blocks():
    rm = RiskManager()
    rm.on_equity(10_000, now=T0)
    rm.on_equity(8_800, now=T0)                    # 12% dd -> halt
    d = rm.evaluate(clean_intent(), now=T0)
    assert not d.ok
    assert d.units == 0
    assert d.drawdown.halted
    assert any("halt" in r for r in d.reasons)


def test_drawdown_tier_reduces_size():
    # Disable the weekly-loss guard so we isolate the drawdown tier ladder.
    rm = RiskManager(RiskConfig(drawdown=dict(weekly_loss_pause_pct=100.0)))
    rm.on_equity(10_000, now=T0)
    state = rm.on_equity(9_600, now=T0)            # 4% dd -> tier 1, 0.75x
    assert state.tier == 1
    d = rm.evaluate(clean_intent(), now=T0)
    assert d.ok
    # notional cap scales with current equity: 9_600 * 4% / 100 = 3.84, then 0.75x
    assert d.units == pytest.approx(3.84 * 0.75)
    assert d.sizing.multipliers_applied.get("drawdown_manager") == 0.75


def test_drawdown_tier3_raises_score_bar():
    rm = RiskManager(RiskConfig(drawdown=dict(weekly_loss_pause_pct=100.0)))
    rm.on_equity(10_000, now=T0)
    state = rm.on_equity(9_200, now=T0)            # 8% dd -> tier 3 (min_score 85)
    assert state.tier == 3

    weak = rm.evaluate(clean_intent(score=80), now=T0)
    assert not weak.ok
    assert any("score" in r for r in weak.reasons)

    strong = rm.evaluate(clean_intent(score=90), now=T0)
    assert strong.ok
    # notional cap on 9_200 equity: 9_200 * 4% / 100 = 3.68, then 0.25x
    assert strong.units == pytest.approx(3.68 * 0.25)


# --------------------------------------------------------------------- session


def test_session_profit_cap_blocks_even_when_validator_passes():
    # The daily profit target is a session-only guard — the validator has no
    # equivalent — so this proves decision.ok ANDs in the session's verdict.
    rm = RiskManager(RiskConfig(session=dict(max_daily_profit_pct=2.0)))
    rm.on_equity(10_000, now=T0)
    rm.on_close(trade_record(pnl=300.0, ts=T0), equity_before=10_000)  # +3% day
    d = rm.evaluate(clean_intent(), now=T0 + timedelta(hours=1))
    assert not d.ok
    assert d.validation.passed                 # the validator itself is happy
    assert d.session.allowed is False
    assert "profit" in d.session.reason
    assert any("session" in r for r in d.reasons)


def test_validator_limits_track_session_config():
    # One knob, both enforcers: setting the session's limits seeds the validator.
    rm = RiskManager(RiskConfig(session=dict(
        max_trades_per_day=9, max_daily_loss_pct=4.0, min_minutes_between_trades=20,
    )))
    assert rm.validator.max_daily_trades == 9
    assert rm.validator.max_daily_loss_pct == 4.0
    assert rm.validator.min_secs_between == 20 * 60
    # An explicit validator override still wins.
    rm2 = RiskManager(RiskConfig(
        session=dict(max_trades_per_day=9),
        validator=dict(max_daily_trades=3),
    ))
    assert rm2.validator.max_daily_trades == 3


def test_total_exposure_cap_tracks_notional_cap():
    # A single full-size position must fit inside the total-exposure cap, so the
    # cap rises with max_notional_pct above the 10% multi-position baseline.
    assert RiskManager(RiskConfig(max_notional_pct=15.0)).validator.max_total_exposure_pct == 15.0
    assert RiskManager(RiskConfig(max_notional_pct=4.0)).validator.max_total_exposure_pct == 10.0
    # An explicit override still wins.
    rm = RiskManager(RiskConfig(
        max_notional_pct=15.0, validator=dict(max_total_exposure_pct=30.0),
    ))
    assert rm.validator.max_total_exposure_pct == 30.0


def test_losing_streak_reduces_size():
    rm = RiskManager()
    rm.on_equity(10_000, now=T0)
    # Wide stop so the risk-based size sits below the notional cap and the
    # reduction is visible in the units (not masked by the cap).
    wide = dict(entry_price=100.0, stop_price=70.0, target_price=160.0)
    baseline = rm.evaluate(clean_intent(**wide), now=T0)
    assert baseline.units == pytest.approx(100.0 / 30.0)

    for _ in range(3):
        rm.on_close(trade_record(pnl=-1.0, ts=T0), equity_before=10_000)
    d = rm.evaluate(clean_intent(**wide), now=T0)
    assert "consecutive_losses>=3" in d.sizing.multipliers_applied
    assert d.units == pytest.approx(baseline.units * 0.5)


def test_bad_risk_reward_blocks():
    rm = RiskManager()
    rm.on_equity(10_000, now=T0)
    d = rm.evaluate(clean_intent(target_price=101.0), now=T0)  # reward 1, risk 2
    assert not d.ok
    assert any("rr_ratio" in r for r in d.reasons)


def test_zero_distance_stop_skips():
    rm = RiskManager()
    rm.on_equity(10_000, now=T0)
    d = rm.evaluate(clean_intent(stop_price=100.0), now=T0)    # entry == stop
    assert not d.ok
    assert d.units == 0
    assert d.sizing.reason_for_zero is not None


# --------------------------------------------------------------- correlation/book


def test_correlation_block():
    rm = RiskManager(RiskConfig(
        correlation=dict(static_groups={"majors": {"BTC/USDT", "ETH/USDT"}})
    ))
    rm.on_equity(10_000, now=T0)
    d1 = rm.evaluate(clean_intent(symbol="BTC/USDT"), now=T0)
    assert d1.ok
    rm.on_fill(d1)
    d2 = rm.evaluate(clean_intent(symbol="ETH/USDT"), now=T0)
    assert not d2.ok
    assert d2.correlation.allowed is False
    assert any("correlation" in r for r in d2.reasons)


def test_on_fill_tracks_exposure_and_total_cap():
    rm = RiskManager()
    rm.on_equity(10_000, now=T0)
    for sym in ("A", "B"):
        d = rm.evaluate(clean_intent(symbol=sym), now=T0)
        assert d.ok
        rm.on_fill(d)
    assert rm.open_symbols() == {"A", "B"}
    assert rm.exposure_pct() == pytest.approx(8.0)            # 2 x 400 / 10_000

    d3 = rm.evaluate(clean_intent(symbol="C"), now=T0)        # 8 + 4 = 12% > 10%
    assert not d3.ok
    assert any("exposure" in r for r in d3.reasons)


def test_concurrency_cap_blocks():
    rm = RiskManager(RiskConfig(max_concurrent=1))
    rm.on_equity(10_000, now=T0)
    d1 = rm.evaluate(clean_intent(symbol="A"), now=T0)
    rm.on_fill(d1)
    d2 = rm.evaluate(clean_intent(symbol="B"), now=T0)
    assert not d2.ok
    assert any("concurrent" in r for r in d2.reasons)


def test_portfolio_heat_cap_blocks_when_total_risk_exceeds():
    rm = RiskManager(RiskConfig(max_portfolio_heat_pct=2.5))
    rm.on_equity(10_000, now=T0)
    # Wide stop → each trade risks ~1% of equity (risk-based, below the notional cap).
    wide = dict(entry_price=100.0, stop_price=50.0, target_price=200.0)
    for sym in ("A", "B"):
        d = rm.evaluate(clean_intent(symbol=sym, **wide), now=T0)
        assert d.ok
        rm.on_fill(d)
    assert rm.portfolio_heat_pct() == pytest.approx(2.0)        # 2 x 1%

    d3 = rm.evaluate(clean_intent(symbol="C", **wide), now=T0)  # projected 3% > 2.5%
    assert not d3.ok
    assert any("heat" in r for r in d3.reasons)


def test_no_heat_cap_by_default():
    rm = RiskManager()
    rm.on_equity(10_000, now=T0)
    d = rm.evaluate(clean_intent(entry_price=100.0, stop_price=50.0, target_price=200.0), now=T0)
    assert not any(c.name == "portfolio_heat_ok" for c in d.validation.details)


def test_sector_exposure_cap_blocks_concentration_but_allows_other_sectors():
    # Raise the total-exposure cap out of the way so only the sector cap can bite.
    rm = RiskManager(RiskConfig(
        max_exposure_per_sector_pct=6.0,
        validator=dict(max_total_exposure_pct=100.0),
    ))
    rm.on_equity(10_000, now=T0)

    d1 = rm.evaluate(clean_intent(symbol="AAPL", sector="tech"), now=T0)
    assert d1.ok
    rm.on_fill(d1)
    assert rm.sector_exposure_pct("tech") == pytest.approx(4.0)   # 400 / 10_000

    # A second tech trade would push 'tech' to 8% > 6% → blocked on the sector cap.
    blocked = rm.evaluate(clean_intent(symbol="MSFT", sector="tech"), now=T0)
    assert not blocked.ok
    assert any("sector" in r for r in blocked.reasons)

    # The same trade in a different sector is fine (energy at 4% < 6%).
    other = rm.evaluate(clean_intent(symbol="XOM", sector="energy"), now=T0)
    assert other.ok


def test_sector_exposure_breakdown_tracks_tagged_positions():
    rm = RiskManager(RiskConfig(validator=dict(max_total_exposure_pct=100.0)))
    rm.on_equity(10_000, now=T0)
    for sym, sector in [("AAPL", "tech"), ("MSFT", "tech"), ("XOM", "energy")]:
        rm.on_fill(rm.evaluate(clean_intent(symbol=sym, sector=sector), now=T0))
    assert rm.sector_exposure() == pytest.approx({"tech": 8.0, "energy": 4.0})


def test_no_sector_cap_by_default():
    rm = RiskManager()
    rm.on_equity(10_000, now=T0)
    d = rm.evaluate(clean_intent(sector="tech"), now=T0)
    assert not any(c.name == "sector_exposure_ok" for c in d.validation.details)


def test_sector_cap_ignores_untagged_trades():
    rm = RiskManager(RiskConfig(max_exposure_per_sector_pct=4.0))
    rm.on_equity(10_000, now=T0)
    d = rm.evaluate(clean_intent(), now=T0)   # no sector tag → cap does not apply
    assert not any(c.name == "sector_exposure_ok" for c in d.validation.details)


def test_on_close_frees_slot_and_feeds_session():
    rm = RiskManager()
    rm.on_equity(10_000, now=T0)
    d = rm.evaluate(clean_intent(symbol="A"), now=T0)
    rm.on_fill(d)
    assert "A" in rm.open_symbols()

    rm.on_close(trade_record(pnl=50.0, symbol="A", ts=T0), equity_before=10_000)
    assert "A" not in rm.open_symbols()
    assert rm.session.day_trades == 1
