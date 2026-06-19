"""Integration example: riskkit inside a freqtrade strategy.

freqtrade lets a strategy override how much to stake per trade via the
``custom_stake_amount`` callback. That's the natural seam for riskkit's
PositionSizer — your entry/exit signals stay in ``populate_*``, and the risk
model decides size.

This is a documented snippet, not a runnable script (freqtrade is a large
dependency and runs its own process). Drop these methods into your
``IStrategy`` subclass.
"""
from riskkit import PositionSizer, SizingInputs

# A single risk policy for the whole strategy.
_SIZER = PositionSizer(base_risk_pct=1.0, max_notional_pct=4.0)


def custom_stake_amount(
    self,
    pair: str,
    current_time,
    current_rate: float,
    proposed_stake: float,
    min_stake,
    max_stake: float,
    leverage: float,
    entry_tag,
    side: str,
    **kwargs,
) -> float:
    """Size the trade with riskkit instead of a flat stake.

    Assumes you've stashed an ATR and a stop price for ``pair`` (e.g. computed in
    ``populate_indicators`` / ``confirm_trade_entry``). ``self.wallets`` gives
    total equity.
    """
    equity = self.wallets.get_total_stake_amount()
    atr = self.custom_info[pair]["atr"]
    atr_baseline = self.custom_info[pair]["atr_baseline"]
    stop_price = self.custom_info[pair]["stop_price"]

    sized = _SIZER.size(SizingInputs(
        equity=equity,
        entry_price=current_rate,
        stop_price=stop_price,
        atr=atr,
        atr_baseline=atr_baseline,
    ))
    if sized.units <= 0:
        return 0.0  # riskkit vetoed the size -> freqtrade skips the entry

    # Clamp the riskkit notional into freqtrade's allowed stake range.
    stake = sized.notional
    if max_stake:
        stake = min(stake, max_stake)
    if min_stake:
        stake = max(stake, min_stake)
    return stake


# For exits, riskkit's StopEngine is bar-driven (see examples/pipeline.py and
# examples/backtesting_py_strategy.py). In freqtrade you'd advance a StopStack in
# `custom_stoploss` using the latest candle, then return the active stop as a
# ratio relative to current_rate.
