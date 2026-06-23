"""Pre-trade validator — the final gate before an order goes out.

A composable checklist that runs every rule against a proposed trade and vetoes
it if *any* rule fails. The point is to make "should I take this trade?" a
single, auditable function call whose output records exactly which rules passed
and which failed.

The checks span market quality, position sizing, risk limits, signal quality,
and timing. The validator is framework-agnostic: you assemble a
:class:`TradeProposal` from whatever your system knows, and you get back a
:class:`ValidationResult`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str = ""


@dataclass
class ValidationResult:
    passed: bool
    failures: list[CheckResult]
    details: list[CheckResult] = field(default_factory=list)
    market_quality_failed: bool = False  # if True, the caller may retry shortly


@dataclass
class TradeProposal:
    symbol: str
    side: str                   # "long" | "short"
    entry_price: float
    stop_price: float
    target_price: float
    size_units: float
    notional: float
    strategy: str
    score: int                  # signal-quality score (0-100)
    regime: str = ""

    # Market-quality snapshot
    spread_pct: float = 0.0
    orderbook_depth: float = float("inf")   # quote-currency depth near touch
    recent_atr_spike_x: float = 1.0         # current_atr / baseline_atr
    last_quote_age_sec: float = 0.0

    # Portfolio state
    equity: float = 0.0
    free_balance: float = float("inf")
    current_total_exposure_pct: float = 0.0
    current_portfolio_heat_pct: float = 0.0   # open risk-at-stop, excl. this trade
    sector: str = ""                          # sector / asset-class tag (for per-sector cap)
    current_sector_exposure_pct: float = 0.0  # this sector's open notional %, excl. this trade
    open_concurrent_positions: int = 0
    daily_loss_pct: float = 0.0
    daily_trade_count: int = 0
    drawdown_halted: bool = False
    cooldown_active: bool = False
    correlation_blocked: bool = False
    at_max_concurrent: bool = False
    seconds_since_last_trade: float = float("inf")


class PreTradeValidator:
    def __init__(
        self,
        max_spread_pct_tight: float = 0.05,
        max_spread_pct_default: float = 0.1,
        tight_spread_symbols: set[str] | None = None,
        depth_multiplier: float = 2.0,
        max_recent_atr_spike: float = 3.0,
        max_quote_age_sec: float = 120.0,
        max_notional_pct: float = 4.0,
        max_total_exposure_pct: float = 10.0,
        max_portfolio_heat_pct: float = float("inf"),
        max_exposure_per_sector_pct: float = float("inf"),
        max_daily_loss_pct: float = 1.5,
        max_daily_trades: int = 5,
        min_score: int = 70,
        min_rr_ratio: float = 2.0,
        min_seconds_between_trades: float = 15 * 60,
        regime_strategies: Mapping[str, set[str]] | None = None,
    ) -> None:
        self.max_spread_tight = max_spread_pct_tight
        self.max_spread_default = max_spread_pct_default
        self.tight_spread_symbols = tight_spread_symbols or set()
        self.depth_mult = depth_multiplier
        self.max_atr_spike = max_recent_atr_spike
        self.max_quote_age = max_quote_age_sec
        self.max_notional_pct = max_notional_pct
        self.max_total_exposure_pct = max_total_exposure_pct
        self.max_portfolio_heat_pct = max_portfolio_heat_pct
        self.max_sector_exposure_pct = max_exposure_per_sector_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_daily_trades = max_daily_trades
        self.min_score = min_score
        self.min_rr = min_rr_ratio
        self.min_secs_between = min_seconds_between_trades
        self.regime_strategies = regime_strategies

    def validate(self, p: TradeProposal, *, min_score_override: int | None = None) -> ValidationResult:
        results: list[CheckResult] = []
        min_score = max(min_score_override or 0, self.min_score)

        # ── MARKET QUALITY ──
        max_spread = (
            self.max_spread_tight if p.symbol in self.tight_spread_symbols
            else self.max_spread_default
        )
        results.append(CheckResult("spread_ok", p.spread_pct < max_spread,
                                   f"spread={p.spread_pct:.4f}% < {max_spread}%"))
        results.append(CheckResult("orderbook_depth_ok",
                                   p.orderbook_depth >= self.depth_mult * p.notional,
                                   f"depth={p.orderbook_depth:.0f} vs {self.depth_mult}x notional {p.notional:.0f}"))
        results.append(CheckResult("no_recent_volatility_spike",
                                   p.recent_atr_spike_x < self.max_atr_spike,
                                   f"atr_spike_x={p.recent_atr_spike_x:.2f} < {self.max_atr_spike}"))
        results.append(CheckResult("data_fresh", p.last_quote_age_sec < self.max_quote_age,
                                   f"quote_age={p.last_quote_age_sec:.0f}s"))

        # ── POSITION SIZING ──
        results.append(CheckResult("size_positive", p.size_units > 0 and p.notional > 0,
                                   "size must be > 0"))
        notional_pct = (p.notional / p.equity * 100.0) if p.equity else 100.0
        results.append(CheckResult("notional_cap", notional_pct <= self.max_notional_pct,
                                   f"notional {notional_pct:.2f}% of equity vs cap {self.max_notional_pct}%"))
        projected = p.current_total_exposure_pct + notional_pct
        results.append(CheckResult("total_exposure_cap", projected <= self.max_total_exposure_pct,
                                   f"projected exposure {projected:.2f}% vs cap {self.max_total_exposure_pct}%"))
        # Per-sector exposure: keep any single sector / asset-class from dominating the
        # book. Only checked when a cap is configured and the trade carries a sector tag.
        if self.max_sector_exposure_pct != float("inf") and p.sector:
            projected_sector = p.current_sector_exposure_pct + notional_pct
            results.append(CheckResult(
                "sector_exposure_ok",
                projected_sector <= self.max_sector_exposure_pct,
                f"sector '{p.sector}' projected {projected_sector:.2f}% vs cap {self.max_sector_exposure_pct}%"))
        # Portfolio heat: total risk-at-stop across open positions plus this one.
        # Only checked when a cap is configured (off by default).
        if self.max_portfolio_heat_pct != float("inf"):
            trade_risk = abs(p.entry_price - p.stop_price) * p.size_units
            trade_risk_pct = (trade_risk / p.equity * 100.0) if p.equity else 0.0
            projected_heat = p.current_portfolio_heat_pct + trade_risk_pct
            results.append(CheckResult("portfolio_heat_ok",
                                       projected_heat <= self.max_portfolio_heat_pct,
                                       f"projected heat {projected_heat:.2f}% vs cap {self.max_portfolio_heat_pct}%"))
        results.append(CheckResult("sufficient_balance", p.free_balance >= p.notional * 1.01,
                                   f"free={p.free_balance:.2f} need={p.notional * 1.01:.2f}"))

        # ── RISK LIMITS ──
        results.append(CheckResult("daily_loss_ok", p.daily_loss_pct < self.max_daily_loss_pct,
                                   f"daily_loss={p.daily_loss_pct:.2f}% < {self.max_daily_loss_pct}%"))
        results.append(CheckResult("daily_trade_count_ok", p.daily_trade_count < self.max_daily_trades,
                                   f"trades_today={p.daily_trade_count} < {self.max_daily_trades}"))
        results.append(CheckResult("not_in_drawdown_halt", not p.drawdown_halted,
                                   "drawdown halt active" if p.drawdown_halted else "ok"))
        results.append(CheckResult("not_in_cooldown", not p.cooldown_active,
                                   "in cooldown" if p.cooldown_active else "ok"))
        results.append(CheckResult("correlation_ok", not p.correlation_blocked,
                                   "correlated position open" if p.correlation_blocked else "ok"))
        results.append(CheckResult("max_concurrent_ok", not p.at_max_concurrent,
                                   f"open={p.open_concurrent_positions} at cap" if p.at_max_concurrent else "ok"))

        # ── SIGNAL QUALITY ──
        results.append(CheckResult("score_ok", p.score >= min_score,
                                   f"score={p.score} >= {min_score}"))
        risk = abs(p.entry_price - p.stop_price)
        reward = abs(p.target_price - p.entry_price)
        rr = reward / risk if risk else 0.0
        results.append(CheckResult("rr_ratio_ok", rr >= self.min_rr,
                                   f"R:R {rr:.2f} >= {self.min_rr}"))
        if self.regime_strategies is not None:
            allowed = p.strategy in self.regime_strategies.get(p.regime, set())
            results.append(CheckResult("regime_allows_strategy", allowed,
                                       f"strategy={p.strategy} regime={p.regime}"))

        # ── TIMING ──
        results.append(CheckResult("min_time_between_trades",
                                   p.seconds_since_last_trade >= self.min_secs_between,
                                   f"{p.seconds_since_last_trade:.0f}s >= {self.min_secs_between}s"))

        failures = [r for r in results if not r.ok]
        market_quality_names = {
            "spread_ok", "orderbook_depth_ok", "no_recent_volatility_spike", "data_fresh",
        }
        return ValidationResult(
            passed=len(failures) == 0,
            failures=failures,
            details=results,
            market_quality_failed=any(r.name in market_quality_names for r in failures),
        )
