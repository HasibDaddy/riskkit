"""End-to-end example: the RiskManager façade.

Run it:  python examples/risk_manager.py

`examples/pipeline.py` wires the six components together by hand. This is the
same flow through the one-object façade: build it once from a single config,
push equity in, and ask one question per trade. The manager keeps the drawdown,
session, and open-book state in sync for you.

Nothing here touches an exchange — you feed in numbers your own system already
has, and you get back an auditable decision.
"""
from datetime import datetime, timedelta, timezone

from riskkit import RiskConfig, RiskManager, TradeIntent, TradeRecord

risk = RiskManager(RiskConfig(
    base_risk_pct=1.0,
    max_notional_pct=4.0,
    max_concurrent=3,
    drawdown=dict(tier1_pct=3, halt_pct=10),
    session=dict(max_trades_per_day=5, min_minutes_between_trades=0),
    correlation=dict(static_groups={"majors": {"BTC/USDT", "ETH/USDT"}}),
))


def show(label: str, decision) -> None:
    if decision.ok:
        print(f"{label:<22} TRADE  {decision.units:.4f} units @ stop {decision.stop} "
              f"(risk {decision.risk_pct:.2%})")
    else:
        print(f"{label:<22} NO TRADE — {decision.reasons[0]}")


now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

# A healthy account taking a clean long.
risk.on_equity(10_000, now=now)
btc = risk.evaluate(TradeIntent(
    symbol="BTC/USDT", side="long",
    entry_price=100.0, stop_price=98.0, target_price=104.0,
    score=82, atr=2.0, atr_baseline=2.0,
), now=now)
show("clean long:", btc)
if btc.ok:
    risk.on_fill(btc)                       # tell riskkit it filled

# A correlated second name — one position per group, so this is vetoed.
eth = risk.evaluate(TradeIntent(
    symbol="ETH/USDT", side="long",
    entry_price=50.0, stop_price=49.0, target_price=52.0, score=80,
), now=now)
show("correlated name:", eth)

# A weak signal on an uncorrelated name — fails the score gate.
sol = risk.evaluate(TradeIntent(
    symbol="SOL/USDT", side="long",
    entry_price=20.0, stop_price=19.5, target_price=21.0, score=55,
), now=now)
show("weak signal:", sol)

# Close the BTC trade for a loss, then watch a drawdown drag the account into a halt.
now += timedelta(hours=1)
risk.on_close(TradeRecord(
    ts_open=now - timedelta(hours=1), ts_close=now, pnl=-200.0, pnl_pct=-2.0,
    score=82, position_size_units=btc.units, duration_minutes=60.0,
    side="long", symbol="BTC/USDT", strategy="default",
), equity_before=10_000)

risk.on_equity(8_900, now=now)              # ~11% drawdown -> halt
halted = risk.evaluate(TradeIntent(
    symbol="ADA/USDT", side="long",
    entry_price=1.0, stop_price=0.98, target_price=1.04, score=90,
), now=now)
show("after drawdown halt:", halted)
print("  reasons:", ", ".join(halted.reasons))
