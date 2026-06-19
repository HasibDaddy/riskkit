"""End-to-end example: wire riskkit's components into one trade decision.

Run it:  python examples/pipeline.py

This shows the intended flow — drawdown posture sets the size multiplier and the
minimum signal bar, the sizer turns risk into units, and the validator is the
final veto. None of this touches an exchange; you feed in numbers your own
system already has.
"""
from riskkit import (
    DrawdownManager,
    PositionSizer,
    PreTradeValidator,
    SizingInputs,
    TradeProposal,
)


def decide_trade(equity: float, entry: float, stop: float, target: float, score: int):
    # 1) Where are we in the drawdown ladder? (drives size + the min-score bar)
    dd = DrawdownManager()
    dd.update(10_100)          # a prior peak
    state = dd.update(equity)  # current equity
    if state.halted:
        return f"NO TRADE — drawdown halt: {state.reason}"

    # 2) Size the position, respecting the drawdown posture.
    sizer = PositionSizer(base_risk_pct=1.0, max_notional_pct=4.0)
    sized = sizer.size(SizingInputs(
        equity=equity,
        entry_price=entry,
        stop_price=stop,
        atr=2.0,
        atr_baseline=2.0,
        confluence_score=score,
        drawdown_pct=state.drawdown_pct,
    ))
    sized.units *= state.size_multiplier
    if sized.units <= 0:
        return f"NO TRADE — sizer skipped: {sized.reason_for_zero}"

    # 3) Final gate: every rule must pass.
    validator = PreTradeValidator(min_score=state.min_score_override or 70)
    result = validator.validate(TradeProposal(
        symbol="BTC/USDT", side="long",
        entry_price=entry, stop_price=stop, target_price=target,
        size_units=sized.units, notional=sized.units * entry,
        strategy="breakout", score=score,
        equity=equity, free_balance=equity,
    ))
    if not result.passed:
        return "NO TRADE — vetoed: " + ", ".join(f.name for f in result.failures)

    return f"TRADE — {sized.units:.4f} units, risk {sized.risk_pct:.2%}, tier {state.tier}"


if __name__ == "__main__":
    print(decide_trade(equity=10_000, entry=100, stop=98, target=104, score=82))  # clean
    print(decide_trade(equity=10_000, entry=100, stop=98, target=104, score=55))  # weak signal
    print(decide_trade(equity=8_900, entry=100, stop=98, target=104, score=82))   # drawdown halt
