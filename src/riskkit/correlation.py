"""Correlation guard.

Stops you from stacking the same risk under different names — opening three
"different" positions that are really one correlated bet. It works from two
sources:

  1. **Static groups** you define (e.g. instruments you know move together).
  2. **Dynamic groups** computed from a rolling return correlation matrix.

Rule: at most one open position per correlation group at a time.

The static-group logic is pure Python with no dependencies. The dynamic
recompute uses pandas, which is an optional extra (``pip install riskkit[pandas]``)
— import it only if you call :meth:`CorrelationGuard.recompute_dynamic`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd


@dataclass
class CorrelationDecision:
    allowed: bool
    reason: str = ""
    blocking_symbol: str | None = None
    group: str | None = None


class CorrelationGuard:
    """Limit concurrent exposure across correlated instruments.

    Parameters
    ----------
    static_groups:
        Named groups of symbols known to move together. Optional.
    dynamic_threshold:
        Absolute return-correlation above which two symbols are grouped
        dynamically.
    lookback_days:
        Rolling window used by :meth:`recompute_dynamic`.
    """

    def __init__(
        self,
        static_groups: Mapping[str, set[str]] | None = None,
        dynamic_threshold: float = 0.75,
        lookback_days: int = 30,
    ) -> None:
        self.static_groups: dict[str, set[str]] = dict(static_groups or {})
        self.dynamic_threshold = dynamic_threshold
        self.lookback_days = lookback_days
        self._dynamic_groups: list[set[str]] = []

    # ----------------------------------------------------------------- dynamic

    def recompute_dynamic(self, daily_closes: "Mapping[str, pd.Series]") -> None:
        """Rebuild dynamic groups from a mapping ``symbol -> daily-close Series``.

        Requires pandas (``pip install riskkit[pandas]``).
        """
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - exercised without pandas
            raise ImportError(
                "recompute_dynamic requires pandas. Install it with "
                "`pip install riskkit[pandas]`."
            ) from exc

        symbols = list(daily_closes.keys())
        if len(symbols) < 2:
            self._dynamic_groups = []
            return

        df = pd.DataFrame(
            {s: daily_closes[s].tail(self.lookback_days * 2) for s in symbols}
        ).dropna()
        if len(df) < self.lookback_days // 2:
            self._dynamic_groups = []
            return

        corr = df.pct_change().dropna().corr().abs()

        groups: list[set[str]] = []
        for i, a in enumerate(symbols):
            for b in symbols[i + 1:]:
                if a == b or pd.isna(corr.loc[a, b]):
                    continue
                if corr.loc[a, b] > self.dynamic_threshold:
                    for g in groups:
                        if a in g or b in g:
                            g.update({a, b})
                            break
                    else:
                        groups.append({a, b})
        self._dynamic_groups = groups

    # ----------------------------------------------------------------- check

    def can_open(self, symbol: str, open_symbols: set[str]) -> CorrelationDecision:
        """Return whether ``symbol`` may be opened given the currently open set."""
        all_groups = list(self.static_groups.items()) + [
            (f"dynamic_{i}", g) for i, g in enumerate(self._dynamic_groups)
        ]
        for name, members in all_groups:
            if symbol not in members:
                continue
            conflict = open_symbols & members
            if conflict:
                return CorrelationDecision(
                    allowed=False,
                    reason=f"correlated with open position in group '{name}'",
                    blocking_symbol=sorted(conflict)[0],
                    group=name,
                )
        return CorrelationDecision(allowed=True)
