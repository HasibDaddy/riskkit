"""freqtrade adapter — risk-managed staking and entry vetoes.

freqtrade strategies are composition-friendly: keep your signals in
``populate_*`` and let this helper drive sizing and the entry gate from the
strategy callbacks. ``FreqtradeRiskManager`` imports **nothing** from freqtrade —
you pass it the values freqtrade hands your callbacks, and it returns what those
callbacks should return. That keeps the riskkit core dependency-free and means
the adapter is fully unit-testable without installing freqtrade.

Wire it into your ``IStrategy`` like this::

    from riskkit import RiskConfig
    from riskkit.adapters.freqtrade import FreqtradeRiskManager

    class MyStrategy(IStrategy):
        def bot_start(self):
            self.risk = FreqtradeRiskManager(RiskConfig.balanced())

        def custom_stake_amount(self, pair, current_time, current_rate,
                                proposed_stake, min_stake, max_stake,
                                leverage, entry_tag, side, **kwargs):
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

        def confirm_trade_entry(self, pair, *args, **kwargs):
            allowed = self.risk.confirm_entry(pair)
            if allowed:
                self.risk.on_fill(pair)        # register it in the open book
            return allowed

A returned stake of ``0.0`` tells freqtrade to skip the entry, so sizing and the
veto can both live in ``custom_stake_amount`` if you prefer a single callback.
"""
from __future__ import annotations

from datetime import datetime

from ..manager import RiskConfig, RiskDecision, RiskManager, TradeIntent
from ..session import TradeRecord


class FreqtradeRiskManager:
    """Drives a :class:`~riskkit.RiskManager` from freqtrade's callback signatures.

    For cross-pair features (correlation, total exposure, concurrency) to work,
    call :meth:`on_fill` once an entry is confirmed and :meth:`on_exit` when a
    trade closes, so the open book and session state stay current.
    """

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.risk = RiskManager(config or RiskConfig())
        self._last: dict[str, RiskDecision] = {}

    # ------------------------------------------------------------------ entry

    def stake_amount(
        self, *, pair: str, equity: float, current_rate: float, stop_price: float,
        max_stake: float, min_stake: float = 0.0, target_price: float | None = None,
        side: str = "long", score: int = 100, now: datetime | None = None,
        **intent_kwargs,
    ) -> float:
        """Riskkit-sized stake (quote currency) for ``custom_stake_amount``.

        Returns ``0.0`` when riskkit vetoes the entry or the size would fall below
        ``min_stake`` — both of which make freqtrade skip the trade. The result is
        also cached so :meth:`confirm_entry` can mirror the same decision.

        ``target_price`` is optional: freqtrade trades are usually exited by ROI /
        trailing stops rather than a fixed target, so when it is omitted a target
        that exactly meets the configured minimum reward:risk is assumed (the R:R
        gate stays neutral). Extra keyword arguments flow to :class:`TradeIntent`.
        """
        if target_price is None:
            risk = abs(current_rate - stop_price)
            rr = self.risk.validator.min_rr
            target_price = (
                current_rate + rr * risk if side == "long" else current_rate - rr * risk
            )

        self.risk.on_equity(equity, now=now)
        decision = self.risk.evaluate(
            TradeIntent(
                symbol=pair, side=side, entry_price=current_rate,
                stop_price=stop_price, target_price=target_price,
                score=score, **intent_kwargs,
            ),
            now=now,
        )
        self._last[pair] = decision
        if not decision.ok:
            return 0.0

        stake = decision.notional
        if max_stake:
            stake = min(stake, float(max_stake))
        if min_stake and stake < float(min_stake):
            return 0.0
        return stake

    def confirm_entry(self, pair: str) -> bool:
        """Mirror the cached decision in ``confirm_trade_entry``. ``True`` allows it."""
        decision = self._last.get(pair)
        return bool(decision and decision.ok)

    def last_decision(self, pair: str) -> RiskDecision | None:
        """The most recent :class:`RiskDecision` for ``pair`` (e.g. to log veto reasons)."""
        return self._last.get(pair)

    # ------------------------------------------------------------------ book

    def on_fill(self, pair: str) -> None:
        """Register a confirmed entry in the open book (call after confirmation)."""
        decision = self._last.get(pair)
        if decision and decision.ok:
            self.risk.on_fill(decision)

    def on_exit(
        self, *, pair: str, pnl: float, pnl_pct: float,
        open_time: datetime, close_time: datetime, amount: float = 0.0,
        side: str = "long", strategy: str = "default",
        equity_before: float | None = None,
    ) -> None:
        """Feed a closed trade back to the session manager (streaks, cooldowns, day P&L)."""
        duration = 0.0
        if isinstance(open_time, datetime) and isinstance(close_time, datetime):
            duration = (close_time - open_time).total_seconds() / 60.0
        self.risk.on_close(
            TradeRecord(
                ts_open=open_time, ts_close=close_time,
                pnl=pnl, pnl_pct=pnl_pct, score=100,
                position_size_units=abs(amount), duration_minutes=duration,
                side=side, symbol=pair, strategy=strategy,
            ),
            equity_before=equity_before,
        )
