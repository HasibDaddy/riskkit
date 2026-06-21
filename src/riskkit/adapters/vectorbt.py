"""vectorbt adapter — size an array of signals with riskkit.

vectorbt is vectorized; riskkit's drawdown and session guards are inherently
sequential, so they don't map onto a single vectorized pass. What *does* map
cleanly is **sizing**: given equity and per-bar entry / stop / volatility, produce
an array of position sizes to feed vectorbt as ``size=``.

:func:`size_signals` does exactly that. It imports nothing from vectorbt and
returns a plain list, so it works with ``vbt.Portfolio.from_signals``, your own
vectorized loop, or pandas. Per-trade drawdown control is supported by passing a
``drawdown_pct`` series (from whatever equity proxy you have) — it feeds the
sizer's reduction ladder. The *stateful* guards (drawdown halting, session caps)
need the sequential :class:`~riskkit.RiskManager`; see the backtesting.py adapter.

Example::

    import vectorbt as vbt
    from riskkit.adapters.vectorbt import size_signals

    sizes = size_signals(
        equity=10_000,
        entry_prices=close.where(entries),     # price where entering, else NaN
        stop_prices=close * 0.97,
        atr=atr, atr_baseline=atr.rolling(100).mean(),
    )
    pf = vbt.Portfolio.from_signals(close, entries, exits,
                                    size=sizes, size_type="value")
"""
from __future__ import annotations

from math import isnan
from typing import Sequence

from ..sizing import PositionSizer, SizingInputs


def _as_list(value, n: int, name: str) -> list:
    """Normalize a scalar or sequence to a length-``n`` list (pandas/numpy safe)."""
    if value is None:
        return [None] * n
    if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
        seq = list(value)
        if len(seq) != n:
            raise ValueError(f"{name} has length {len(seq)}, expected {n}")
        return seq
    return [value] * n


def _is_entry(price) -> bool:
    """A bar is an entry where the entry price is present and positive."""
    if price is None:
        return False
    try:
        if isnan(price):
            return False
    except TypeError:
        return False
    return price > 0


def size_signals(
    *,
    equity,
    entry_prices: Sequence[float],
    stop_prices: Sequence[float],
    atr=None,
    atr_baseline=None,
    drawdown_pct=None,
    sizer: PositionSizer | None = None,
    return_fraction: bool = True,
) -> list[float]:
    """Size each entry signal with riskkit's :class:`PositionSizer`.

    Parameters
    ----------
    equity:
        Account equity — a scalar (fixed-fractional on a constant base) or a
        per-bar sequence (e.g. a rolling equity estimate).
    entry_prices:
        Entry price at each bar; use ``NaN`` / ``0`` / ``None`` on bars with no
        entry. This array drives where a non-zero size is produced.
    stop_prices:
        Stop price at each bar (defines risk-per-unit).
    atr, atr_baseline:
        Optional volatility and its baseline for the sizer's vol scaling
        (scalar or per-bar). Omitted ⇒ no vol scaling.
    drawdown_pct:
        Optional per-bar drawdown percentage fed to the sizer's reduction ladder.
    sizer:
        A configured :class:`PositionSizer` (defaults to ``PositionSizer()``).
    return_fraction:
        When ``True`` (default) each element is ``notional / equity`` (use vectorbt
        ``size_type="value"``/percent); when ``False`` it is units (``"amount"``).

    Returns
    -------
    A list the same length as ``entry_prices``: the size on entry bars, ``0.0``
    elsewhere (and where the sizer vetoes the trade).
    """
    sizer = sizer or PositionSizer()
    n = len(entry_prices)
    eq = _as_list(equity, n, "equity")
    entries = list(entry_prices)
    stops = _as_list(stop_prices, n, "stop_prices")
    atrs = _as_list(atr, n, "atr")
    bases = _as_list(atr_baseline, n, "atr_baseline")
    dds = _as_list(drawdown_pct, n, "drawdown_pct")

    sizes: list[float] = []
    for i in range(n):
        entry = entries[i]
        if not _is_entry(entry) or eq[i] is None or stops[i] is None:
            sizes.append(0.0)
            continue
        result = sizer.size(SizingInputs(
            equity=float(eq[i]),
            entry_price=float(entry),
            stop_price=float(stops[i]),
            atr=float(atrs[i]) if atrs[i] is not None else 0.0,
            atr_baseline=float(bases[i]) if bases[i] is not None else 0.0,
            drawdown_pct=float(dds[i]) if dds[i] is not None else 0.0,
        ))
        if result.units <= 0:
            sizes.append(0.0)
        elif return_fraction:
            sizes.append(result.notional / float(eq[i]) if eq[i] else 0.0)
        else:
            sizes.append(result.units)
    return sizes
