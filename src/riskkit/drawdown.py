"""Drawdown manager.

Tracks high-water-mark equity and the resulting drawdown, then maps it onto a
tier ladder. Each tier dials position size down, raises the bar for taking new
trades, and eventually halts entirely. A recovery ramp prevents the manager
from snapping straight back to full size the moment equity ticks up — it has to
earn its way back one tier at a time.

Default tiers::

    0    dd <= tier1      normal
    1    tier1 < dd <= tier2    0.75x size
    2    tier2 < dd <= tier3    0.50x size, min_score 80
    3    tier3 < dd <= halt     0.25x size, min_score 85, max 1 concurrent
    4    dd > halt              HALT — no new entries

A separate weekly-loss guard pauses new entries for 24h if equity falls more
than ``weekly_loss_pause_pct`` within a rolling 7-day window.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class DrawdownState:
    """The current risk posture implied by drawdown.

    ``size_multiplier`` scales position size; ``min_score_override`` and
    ``max_concurrent_override`` are ``None`` when the tier imposes no override.
    When ``halted`` is True, no new entries should be opened.
    """

    tier: int
    drawdown_pct: float
    peak_equity: float
    halted: bool
    size_multiplier: float
    min_score_override: int | None
    max_concurrent_override: int | None
    reason: str = ""


@dataclass
class _WeeklyWindow:
    start_equity: float
    start_ts: datetime


class DrawdownManager:
    """Stateful drawdown tracker. Call :meth:`update` once per equity refresh.

    All threshold arguments are human percentages (``3.0`` == 3% drawdown).
    """

    def __init__(
        self,
        tier1_pct: float = 3.0,
        tier2_pct: float = 5.0,
        tier3_pct: float = 7.0,
        halt_pct: float = 10.0,
        weekly_loss_pause_pct: float = 3.0,
        recovery_ramp: bool = True,
    ) -> None:
        self.tier1 = tier1_pct
        self.tier2 = tier2_pct
        self.tier3 = tier3_pct
        self.halt = halt_pct
        self.weekly_loss = weekly_loss_pause_pct
        self.recovery_ramp = recovery_ramp

        self.peak_equity: float = 0.0
        self.current_tier: int = 0
        self.weekly_window: _WeeklyWindow | None = None
        self.weekly_pause_until: datetime | None = None

    def update(self, equity: float, now: datetime | None = None) -> DrawdownState:
        """Feed the latest equity and get back the current :class:`DrawdownState`."""
        now = now or datetime.now(timezone.utc)
        if equity <= 0:
            return DrawdownState(
                4, 100.0, self.peak_equity, True, 0.0, None, None,
                reason="non-positive equity",
            )

        if equity > self.peak_equity:
            self.peak_equity = equity

        dd_pct = (
            (self.peak_equity - equity) / self.peak_equity * 100.0
            if self.peak_equity else 0.0
        )

        target = self._target_tier(dd_pct)

        # Recovery ramp: a tier can only step DOWN one level at a time, and only
        # once drawdown has recovered to half of the lower tier's threshold.
        if self.recovery_ramp and target < self.current_tier:
            lower_threshold = [self.tier1, self.tier2, self.tier3, self.halt][
                max(0, self.current_tier - 1)
            ]
            if dd_pct < lower_threshold * 0.5:
                self.current_tier = max(target, self.current_tier - 1)
            # otherwise hold at the current tier
        else:
            self.current_tier = target

        weekly_loss = self._update_weekly_window(equity, now)

        size_mult, min_score, max_conc, halted, reason = self._tier_actions(
            self.current_tier, weekly_pause=self.weekly_pause_until is not None
        )

        return DrawdownState(
            tier=self.current_tier,
            drawdown_pct=dd_pct,
            peak_equity=self.peak_equity,
            halted=halted,
            size_multiplier=size_mult,
            min_score_override=min_score,
            max_concurrent_override=max_conc,
            reason=reason,
        )

    # ------------------------------------------------------------------ helpers

    def _target_tier(self, dd_pct: float) -> int:
        if dd_pct > self.halt:
            return 4
        if dd_pct > self.tier3:
            return 3
        if dd_pct > self.tier2:
            return 2
        if dd_pct > self.tier1:
            return 1
        return 0

    def _update_weekly_window(self, equity: float, now: datetime) -> float:
        """Maintain the rolling 7-day window and arm/clear the weekly pause."""
        if self.weekly_window is None or (now - self.weekly_window.start_ts).days >= 7:
            self.weekly_window = _WeeklyWindow(start_equity=equity, start_ts=now)

        weekly_loss = (
            (self.weekly_window.start_equity - equity)
            / self.weekly_window.start_equity * 100.0
        )

        if weekly_loss > self.weekly_loss and self.weekly_pause_until is None:
            self.weekly_pause_until = now + timedelta(hours=24)

        if self.weekly_pause_until and now >= self.weekly_pause_until:
            self.weekly_pause_until = None

        return weekly_loss

    @staticmethod
    def _tier_actions(
        tier: int, weekly_pause: bool
    ) -> tuple[float, int | None, int | None, bool, str]:
        if weekly_pause:
            return 0.0, None, 0, True, "weekly loss limit — 24h pause"
        if tier == 0:
            return 1.0, None, None, False, "normal"
        if tier == 1:
            return 0.75, None, None, False, "tier1 — size 0.75x"
        if tier == 2:
            return 0.5, 80, None, False, "tier2 — size 0.5x, min_score 80"
        if tier == 3:
            return 0.25, 85, 1, False, "tier3 — size 0.25x, min_score 85, max 1 position"
        return 0.0, None, 0, True, "HALT — drawdown exceeded halt threshold"
