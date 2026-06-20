"""RiskManager — the one-object façade over all of riskkit.

The individual components (:class:`PositionSizer`, :class:`DrawdownManager`,
:class:`StopEngine`, :class:`CorrelationGuard`, :class:`SessionManager`,
:class:`PreTradeValidator`) are deliberately small and independent so you can
reach for exactly one. But most systems want all of them, wired together, with
state flowing between them — the drawdown tier should shrink the position the
sizer hands back; the session's losing streak should feed the sizer's reduction
ladder; the open book should drive the correlation and exposure checks.

``RiskManager`` does that wiring. You build it once from a single
:class:`RiskConfig`, push equity into it as your account moves, and then ask one
question per trade::

    from riskkit import RiskManager, RiskConfig, TradeIntent

    risk = RiskManager(RiskConfig(
        base_risk_pct=1.0, max_notional_pct=4.0,
        drawdown=dict(tier1_pct=3, halt_pct=10),
        session=dict(max_trades_per_day=5),
    ))

    risk.on_equity(equity)                          # refresh drawdown/session state
    decision = risk.evaluate(TradeIntent(
        symbol="BTC/USDT", side="long",
        entry_price=100.0, stop_price=98.0, target_price=104.0,
        score=82, atr=2.0, atr_baseline=2.0,
    ))
    if decision.ok:
        place(decision.units, decision.stop)        # your execution layer
        risk.on_fill(decision)                       # tell riskkit it filled
    ...
    risk.on_close(trade_record)                      # when the position closes

Nothing here talks to an exchange or a backtester. You feed it numbers and it
hands back an auditable :class:`RiskDecision`: how big, where the stop sits, and
— when it says no — every reason why.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from math import inf

from .correlation import CorrelationDecision, CorrelationGuard
from .drawdown import DrawdownManager, DrawdownState
from .session import SessionDecision, SessionManager, TradeRecord
from .sizing import PositionSizer, SizingInputs, SizingResult
from .stops import StopEngine
from .validator import PreTradeValidator, TradeProposal, ValidationResult

# Mirrors PreTradeValidator's own default; also the façade's multi-position
# baseline for the total-exposure cap.
_DEFAULT_TOTAL_EXPOSURE_PCT = 10.0


@dataclass
class RiskConfig:
    """One config for the whole stack.

    The two knobs people change most often — ``base_risk_pct`` (risk per trade)
    and ``max_notional_pct`` (the hard size ceiling) — are promoted to the top
    level and flow into both the sizer and the validator so the two never
    disagree. Everything else is configured per component: each of the dict
    fields below is passed straight through as keyword arguments to the matching
    component's constructor, so any argument that component accepts works here.

    Example::

        RiskConfig(
            base_risk_pct=0.75,
            max_notional_pct=4.0,
            max_concurrent=3,
            drawdown=dict(tier1_pct=3, halt_pct=10),
            session=dict(max_trades_per_day=5, min_minutes_between_trades=30),
            correlation=dict(static_groups={"majors": {"BTC/USDT", "ETH/USDT"}}),
        )
    """

    # Promoted convenience knobs (feed sizer + validator).
    base_risk_pct: float = 1.0
    max_notional_pct: float = 4.0
    # A baseline cap on concurrently open positions (None = unlimited). The
    # drawdown manager can tighten this further at deep tiers.
    max_concurrent: int | None = None

    # Per-component overrides — passed verbatim to each constructor.
    sizing: dict = field(default_factory=dict)
    drawdown: dict = field(default_factory=dict)
    stops: dict = field(default_factory=dict)
    correlation: dict = field(default_factory=dict)
    session: dict = field(default_factory=dict)
    validator: dict = field(default_factory=dict)


@dataclass
class TradeIntent:
    """A trade you are considering, *before* riskkit has sized or vetted it.

    You fill in what your strategy knows — the instrument, direction, the entry,
    where the stop and target sit, and a 0–100 signal ``score`` — plus whatever
    market-quality and (optional) edge statistics you have. riskkit supplies the
    rest: how big the position should be, and whether it clears every gate.

    The per-trade risk factors the sizer's reduction ladder needs (drawdown,
    losing streak, daily loss) are **not** asked for here — the manager derives
    them from the equity you push in and the trades you record, so they can never
    drift out of sync with reality.
    """

    symbol: str
    side: str                       # "long" | "short"
    entry_price: float
    stop_price: float
    target_price: float
    score: int = 100                # signal-quality score (0-100)
    strategy: str = "default"
    regime: str = ""

    # Volatility scaling for the sizer (optional; left at 0 → no vol scaling).
    atr: float = 0.0
    atr_baseline: float = 0.0
    # Defaults to ``score`` when None; drives the sizer's conviction bonus.
    confluence_score: int | None = None

    # Market-quality snapshot (fed to the validator).
    spread_pct: float = 0.0
    orderbook_depth: float = inf
    recent_atr_spike_x: float = 1.0
    last_quote_age_sec: float = 0.0
    free_balance: float = inf

    # Optional historical edge → enables the sizer's half-Kelly ceiling.
    win_rate: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None


@dataclass
class OpenPosition:
    """A position the manager believes is currently open.

    Tracked so the correlation guard, exposure cap, and concurrency cap have
    something to reason about. Registered via :meth:`RiskManager.on_fill` and
    cleared by :meth:`RiskManager.on_close`.
    """

    symbol: str
    side: str
    units: float
    notional: float
    entry_price: float
    stop_price: float
    strategy: str = "default"


@dataclass
class RiskDecision:
    """The answer to "should I take this trade, and how big?".

    ``ok`` is the bottom line. When it is ``True``, ``units`` and ``stop`` are
    ready to send to your execution layer. When it is ``False``, ``reasons`` lists
    every gate that blocked it, and the component results below let you inspect
    exactly what happened.
    """

    ok: bool
    symbol: str
    side: str
    units: float
    notional: float
    entry: float
    stop: float
    target: float
    risk_pct: float
    risk_amount: float
    reasons: list[str] = field(default_factory=list)

    # Full component results, for auditing.
    sizing: SizingResult | None = None
    validation: ValidationResult | None = None
    drawdown: DrawdownState | None = None
    session: SessionDecision | None = None
    correlation: CorrelationDecision | None = None

    def __bool__(self) -> bool:  # `if decision:` reads the same as `decision.ok`
        return self.ok


class RiskManager:
    """Wires all six riskkit components together behind one config and one call.

    Build it from a :class:`RiskConfig`, call :meth:`on_equity` whenever your
    account value changes, and :meth:`evaluate` for each trade you are
    considering. Tell it about fills and closes (:meth:`on_fill` /
    :meth:`on_close`) so the open book, drawdown, and session state stay current.

    The underlying components are exposed as attributes (``.sizer``, ``.drawdown``,
    ``.stops``, ``.correlation``, ``.session``, ``.validator``) for when you need
    to reach past the façade.
    """

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

        # Promote the headline knobs, letting a per-component dict override them.
        sizing_kwargs = {
            "base_risk_pct": self.config.base_risk_pct,
            "max_notional_pct": self.config.max_notional_pct,
            **self.config.sizing,
        }

        self.sizer = PositionSizer(**sizing_kwargs)
        self.drawdown = DrawdownManager(**self.config.drawdown)
        self.stops = StopEngine(**self.config.stops)
        self.correlation = CorrelationGuard(**self.config.correlation)
        self.session = SessionManager(**self.config.session)

        # Seed the validator from the headline knob and the session's effective
        # limits, so the two enforcers never silently disagree on the same
        # threshold. Anything in ``config.validator`` still wins if set.
        validator_kwargs = {
            "max_notional_pct": self.config.max_notional_pct,
            # A single full-size position must fit inside the total-exposure cap,
            # so the cap tracks max_notional_pct when that is raised above the
            # multi-position baseline. An explicit validator override still wins.
            "max_total_exposure_pct": max(
                _DEFAULT_TOTAL_EXPOSURE_PCT, self.config.max_notional_pct
            ),
            "max_daily_trades": self.session.max_trades,
            "max_daily_loss_pct": self.session.max_loss_pct,
            "min_seconds_between_trades": self.session.min_minutes_between * 60,
            **self.config.validator,
        }
        self.validator = PreTradeValidator(**validator_kwargs)

        self._equity: float | None = None
        self._dd_state: DrawdownState | None = None
        self._open: dict[str, OpenPosition] = {}

    # ------------------------------------------------------------------ state

    @property
    def equity(self) -> float | None:
        """The most recent equity pushed in via :meth:`on_equity`."""
        return self._equity

    def on_equity(self, equity: float, now: datetime | None = None) -> DrawdownState:
        """Push the latest account equity. Refreshes drawdown state and returns it.

        Call this whenever equity moves (at least once before :meth:`evaluate`).
        """
        self._equity = equity
        self._dd_state = self.drawdown.update(equity, now=now)
        return self._dd_state

    def open_symbols(self) -> set[str]:
        """Symbols the manager currently considers open."""
        return set(self._open)

    @property
    def open_positions(self) -> dict[str, OpenPosition]:
        """A copy of the open book, keyed by symbol."""
        return dict(self._open)

    def exposure_pct(self) -> float:
        """Total open notional as a percentage of current equity."""
        if not self._equity:
            return 0.0
        return sum(p.notional for p in self._open.values()) / self._equity * 100.0

    # ------------------------------------------------------------------ evaluate

    def evaluate(self, intent: TradeIntent, now: datetime | None = None) -> RiskDecision:
        """Size and validate a single trade. The heart of the façade.

        Returns a :class:`RiskDecision`. ``decision.ok`` is the AND of the
        pre-trade validator passing *and* the session manager permitting a new
        entry — the latter catches behavioural blocks (tilt, cooldowns, profit
        target hit, strategy halt) that have no dedicated validator flag.
        """
        if self._equity is None or self._dd_state is None:
            raise RuntimeError(
                "call on_equity(...) at least once before evaluate(...)"
            )
        now = now or datetime.now(timezone.utc)
        equity = self._equity
        dd = self._dd_state

        # ---- gather stateful gates ----
        sess = self.session.can_open(intent.strategy, now=now, score=intent.score)
        corr = self.correlation.can_open(intent.symbol, self.open_symbols())

        # ---- size the trade ----
        # The drawdown dimension is applied once, via the manager's size
        # multiplier below — so we leave drawdown_pct out of the sizer to avoid
        # double-counting its own drawdown ladder. The losing-streak and
        # daily-loss factors come straight from recorded session state.
        daily_loss_pct = max(0.0, -self.session.day_pnl_pct)
        sized = self.sizer.size(SizingInputs(
            equity=equity,
            entry_price=intent.entry_price,
            stop_price=intent.stop_price,
            atr=intent.atr,
            atr_baseline=intent.atr_baseline,
            confluence_score=(
                intent.confluence_score if intent.confluence_score is not None
                else intent.score
            ),
            consecutive_losses=self.session.consecutive_losses,
            drawdown_pct=0.0,
            daily_loss_pct=daily_loss_pct,
            win_rate=intent.win_rate,
            avg_win=intent.avg_win,
            avg_loss=intent.avg_loss,
        ))

        dd_mult = dd.size_multiplier
        units = sized.units * dd_mult
        notional = units * intent.entry_price
        risk_per_unit = abs(intent.entry_price - intent.stop_price)
        risk_amount = units * risk_per_unit
        risk_pct = sized.risk_pct * dd_mult

        # Fold the drawdown reduction into the size audit trail.
        applied = dict(sized.multipliers_applied)
        if dd_mult != 1.0:
            applied["drawdown_manager"] = dd_mult
        sized_audit = replace(
            sized, units=units, notional=notional,
            risk_amount=risk_amount, risk_pct=risk_pct,
            multipliers_applied=applied,
        )

        # ---- concurrency ceiling (config baseline tightened by drawdown tier) ----
        # The drawdown manager uses max_concurrent_override == 0 as a "no
        # positions" sentinel during a halt/pause; that case is already reported
        # via the halt flag, so only treat an override of >= 1 as a real cap.
        dd_concurrent = (
            dd.max_concurrent_override
            if (dd.max_concurrent_override or 0) >= 1 else None
        )
        caps = [
            c for c in (self.config.max_concurrent, dd_concurrent)
            if c is not None
        ]
        effective_max = min(caps) if caps else None
        at_max_concurrent = (
            effective_max is not None and len(self._open) >= effective_max
        )

        seconds_since_last = (
            (now - self.session.last_trade_ts).total_seconds()
            if self.session.last_trade_ts else inf
        )
        cooldown_active = (
            bool(sess.cooldown_until is not None and now < sess.cooldown_until)
            or sess.on_tilt
        )

        # ---- final validation gate ----
        proposal = TradeProposal(
            symbol=intent.symbol,
            side=intent.side,
            entry_price=intent.entry_price,
            stop_price=intent.stop_price,
            target_price=intent.target_price,
            size_units=units,
            notional=notional,
            strategy=intent.strategy,
            score=intent.score,
            regime=intent.regime,
            spread_pct=intent.spread_pct,
            orderbook_depth=intent.orderbook_depth,
            recent_atr_spike_x=intent.recent_atr_spike_x,
            last_quote_age_sec=intent.last_quote_age_sec,
            equity=equity,
            free_balance=intent.free_balance,
            current_total_exposure_pct=self.exposure_pct(),
            open_concurrent_positions=len(self._open),
            daily_loss_pct=daily_loss_pct,
            daily_trade_count=self.session.day_trades,
            drawdown_halted=dd.halted,
            cooldown_active=cooldown_active,
            correlation_blocked=not corr.allowed,
            at_max_concurrent=at_max_concurrent,
            seconds_since_last_trade=seconds_since_last,
        )
        validation = self.validator.validate(
            proposal, min_score_override=dd.min_score_override
        )

        ok = validation.passed and sess.allowed
        reasons: list[str] = [f"{f.name}: {f.details}" for f in validation.failures]
        if not sess.allowed:
            reasons.append(f"session: {sess.reason}")

        return RiskDecision(
            ok=ok,
            symbol=intent.symbol,
            side=intent.side,
            units=units,
            notional=notional,
            entry=intent.entry_price,
            stop=intent.stop_price,
            target=intent.target_price,
            risk_pct=risk_pct,
            risk_amount=risk_amount,
            reasons=reasons,
            sizing=sized_audit,
            validation=validation,
            drawdown=dd,
            session=sess,
            correlation=corr,
        )

    # ------------------------------------------------------------------ book

    def on_fill(self, decision: RiskDecision, strategy: str = "default") -> OpenPosition:
        """Record that an evaluated trade was actually filled.

        Adds it to the open book so subsequent correlation, exposure, and
        concurrency checks account for it. Pass the :class:`RiskDecision` you got
        back from :meth:`evaluate`.
        """
        pos = OpenPosition(
            symbol=decision.symbol,
            side=decision.side,
            units=decision.units,
            notional=decision.notional,
            entry_price=decision.entry,
            stop_price=decision.stop,
            strategy=strategy,
        )
        self._open[pos.symbol] = pos
        return pos

    def on_close(
        self,
        trade: TradeRecord,
        equity_before: float | None = None,
    ) -> None:
        """Record a closed trade: feed the session manager and free the slot.

        ``equity_before`` defaults to the manager's last-known equity; it scales
        the trade's PnL into the session's daily-loss percentage.
        """
        self.session.record_trade(
            trade, equity_before if equity_before is not None else (self._equity or 0.0)
        )
        self._open.pop(trade.symbol, None)
