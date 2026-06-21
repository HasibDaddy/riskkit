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


def test_portfolio_heat_check_only_when_configured():
    # Off by default: the check is not even present.
    assert not any(c.name == "portfolio_heat_ok"
                   for c in PreTradeValidator().validate(clean_proposal()).details)

    # With a cap, projected heat = current open heat + this trade's risk.
    v = PreTradeValidator(max_portfolio_heat_pct=3.0)
    blocked = v.validate(clean_proposal(current_portfolio_heat_pct=3.5))
    assert any(f.name == "portfolio_heat_ok" for f in blocked.failures)
    assert v.validate(clean_proposal(current_portfolio_heat_pct=1.0)).passed
