"""Tests for riskkit.validator.PreTradeValidator."""
from riskkit import PreTradeValidator, TradeProposal


def clean_proposal(**overrides):
    """A proposal that passes every check by default."""
    defaults = dict(
        symbol="X", side="long",
        entry_price=100.0, stop_price=98.0, target_price=104.0,  # R:R = 2.0
        size_units=1.0, notional=100.0,
        strategy="s", score=80,
        spread_pct=0.0, orderbook_depth=10_000.0,
        recent_atr_spike_x=1.0, last_quote_age_sec=0.0,
        equity=10_000.0, free_balance=10_000.0,
        current_total_exposure_pct=0.0, open_concurrent_positions=0,
        daily_loss_pct=0.0, daily_trade_count=0,
        seconds_since_last_trade=10_000.0,
    )
    defaults.update(overrides)
    return TradeProposal(**defaults)


def test_clean_proposal_passes():
    v = PreTradeValidator()
    r = v.validate(clean_proposal())
    assert r.passed
    assert r.failures == []


def test_weak_score_and_wide_spread_fail():
    v = PreTradeValidator()
    r = v.validate(clean_proposal(score=50, spread_pct=5.0))
    assert not r.passed
    failed = {f.name for f in r.failures}
    assert "score_ok" in failed
    assert "spread_ok" in failed
    assert r.market_quality_failed  # spread is a market-quality check


def test_bad_risk_reward_fails():
    v = PreTradeValidator(min_rr_ratio=2.0)
    r = v.validate(clean_proposal(target_price=101.0))  # reward 1, risk 2 -> R:R 0.5
    assert not r.passed
    assert any(f.name == "rr_ratio_ok" for f in r.failures)


def test_regime_check_only_when_configured():
    # Without a regime map, the regime check is skipped entirely.
    assert PreTradeValidator().validate(clean_proposal(regime="anything")).passed

    v = PreTradeValidator(regime_strategies={"trending": {"ema"}})
    blocked = v.validate(clean_proposal(strategy="rsi", regime="trending"))
    assert any(f.name == "regime_allows_strategy" for f in blocked.failures)
    assert v.validate(clean_proposal(strategy="ema", regime="trending")).passed


def test_halt_flags_block():
    v = PreTradeValidator()
    assert not v.validate(clean_proposal(drawdown_halted=True)).passed
    assert not v.validate(clean_proposal(correlation_blocked=True)).passed


def test_inverted_stop_fails_protective_side_check():
    v = PreTradeValidator()
    # Long with the stop *above* the entry: sized happily via abs() before,
    # must now be vetoed — and not as a retryable market-quality failure.
    r = v.validate(clean_proposal(stop_price=103.0))
    assert not r.passed
    assert any(f.name == "stop_on_protective_side" for f in r.failures)
    assert not r.market_quality_failed

    # Short with the stop *below* the entry.
    r = v.validate(clean_proposal(side="short", stop_price=98.0, target_price=96.0))
    assert not r.passed
    assert any(f.name == "stop_on_protective_side" for f in r.failures)


def test_stop_at_entry_fails_protective_side_check():
    # A stop at the entry protects nothing, either direction.
    v = PreTradeValidator()
    for side in ("long", "short"):
        target = 104.0 if side == "long" else 96.0
        r = v.validate(clean_proposal(side=side, stop_price=100.0, target_price=target))
        assert any(f.name == "stop_on_protective_side" for f in r.failures)


def test_short_with_protective_geometry_passes():
    v = PreTradeValidator()
    r = v.validate(clean_proposal(side="short", stop_price=102.0, target_price=96.0))
    assert r.passed
    assert r.failures == []


def test_inverted_target_fails_profit_side_check():
    v = PreTradeValidator()
    # Long with the target below the entry (stop stays protective).
    r = v.validate(clean_proposal(target_price=97.0))
    assert not r.passed
    assert any(f.name == "target_on_profit_side" for f in r.failures)
    # Short with the target above the entry.
    r = v.validate(clean_proposal(side="short", stop_price=102.0, target_price=103.0))
    assert any(f.name == "target_on_profit_side" for f in r.failures)


def test_geometry_checks_require_known_side():
    # An out-of-contract side string skips the geometry checks rather than guess
    # which direction it means.
    r = PreTradeValidator().validate(clean_proposal(side="buy", stop_price=103.0))
    assert not any(c.name == "stop_on_protective_side" for c in r.details)
    assert not any(c.name == "target_on_profit_side" for c in r.details)


def test_portfolio_heat_check_only_when_configured():
    # Off by default: the check is not even present.
    assert not any(c.name == "portfolio_heat_ok"
                   for c in PreTradeValidator().validate(clean_proposal()).details)

    # With a cap, projected heat = current open heat + this trade's risk.
    v = PreTradeValidator(max_portfolio_heat_pct=3.0)
    blocked = v.validate(clean_proposal(current_portfolio_heat_pct=3.5))
    assert any(f.name == "portfolio_heat_ok" for f in blocked.failures)
    assert v.validate(clean_proposal(current_portfolio_heat_pct=1.0)).passed


def test_sector_exposure_check_only_when_configured_and_tagged():
    # Off by default, even on a tagged trade.
    assert not any(c.name == "sector_exposure_ok"
                   for c in PreTradeValidator().validate(clean_proposal(sector="tech")).details)

    # Configured but untagged → still absent (an empty sector is never capped).
    v = PreTradeValidator(max_exposure_per_sector_pct=5.0)
    assert not any(c.name == "sector_exposure_ok"
                   for c in v.validate(clean_proposal(sector="")).details)

    # Tagged + capped: projected = current sector exposure + this notional (100/10_000 = 1%).
    blocked = v.validate(clean_proposal(sector="tech", current_sector_exposure_pct=4.5))
    assert any(f.name == "sector_exposure_ok" for f in blocked.failures)   # 4.5 + 1 = 5.5 > 5
    assert v.validate(clean_proposal(sector="tech", current_sector_exposure_pct=2.0)).passed  # 3 ≤ 5
