"""Integration example: riskkit inside a freqtrade strategy.

freqtrade is composition-friendly — keep your signals in ``populate_*`` and let
``FreqtradeRiskManager`` drive sizing and the entry veto from the strategy
callbacks. The helper imports nothing from freqtrade (you pass it the values
freqtrade hands your callbacks), so this is a documented snippet you drop into
your own ``IStrategy`` subclass.

See ``riskkit.adapters.freqtrade`` for the full API.
"""
from riskkit import RiskConfig
from riskkit.adapters.freqtrade import FreqtradeRiskManager


class RiskkitFreqtradeMixin:
    """Illustrative IStrategy methods. Mix these into your own strategy."""

    def bot_start(self) -> None:
        # One risk policy for the whole strategy (try a preset to start).
        self.risk = FreqtradeRiskManager(RiskConfig.balanced())

    def custom_stake_amount(
        self, pair, current_time, current_rate, proposed_stake,
        min_stake, max_stake, leverage, entry_tag, side, **kwargs,
    ) -> float:
        """Size the trade with riskkit; returning 0.0 makes freqtrade skip it.

        Assumes you stashed an ATR and stop price for ``pair`` (e.g. in
        ``populate_indicators``). ``self.wallets`` gives total equity.
        """
        info = self.custom_info[pair]
        return self.risk.stake_amount(
            pair=pair, side=side,
            equity=self.wallets.get_total_stake_amount(),
            current_rate=current_rate,
            stop_price=info["stop_price"],
            max_stake=max_stake, min_stake=min_stake,
            score=info.get("score", 100),
            atr=info.get("atr", 0.0), atr_baseline=info.get("atr_baseline", 0.0),
            now=current_time,
        )

    def confirm_trade_entry(self, pair, *args, **kwargs) -> bool:
        """Mirror riskkit's verdict, and register the fill in the open book."""
        allowed = self.risk.confirm_entry(pair)
        if allowed:
            self.risk.on_fill(pair)
        return allowed

    def confirm_trade_exit(self, pair, trade, *args, **kwargs) -> bool:
        """Feed the closed round-trip back so streaks / cooldowns stay live."""
        self.risk.on_exit(
            pair=pair, pnl=trade.calc_profit(rate=kwargs.get("rate")),
            pnl_pct=trade.calc_profit_ratio(rate=kwargs.get("rate")) * 100.0,
            open_time=trade.open_date_utc, close_time=kwargs.get("current_time"),
            amount=trade.amount, side="long",
        )
        return True
