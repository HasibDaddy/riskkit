"""Risk metrics.

Historical Value-at-Risk and Conditional Value-at-Risk (expected shortfall) over
a series of returns. Both are reported as **positive loss magnitudes** — a VaR of
``0.04`` means "at this confidence, losses are not expected to exceed 4%."

Pure standard library; feed it a sequence of period returns (as fractions, e.g.
``-0.02`` for −2%) and it hands back auditable numbers. By construction
``conditional_value_at_risk >= value_at_risk`` (the average tail loss is at least
the threshold loss).
"""
from __future__ import annotations

from typing import Sequence


def _tail(returns: Sequence[float], confidence: float) -> list[float]:
    """The worst ``(1 - confidence)`` fraction of returns, ascending."""
    if not returns:
        raise ValueError("returns must be non-empty")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    ordered = sorted(returns)
    k = max(1, int(round((1.0 - confidence) * len(ordered))))
    return ordered[:k]


def value_at_risk(returns: Sequence[float], confidence: float = 0.95) -> float:
    """Historical VaR — the threshold loss at ``confidence`` (positive = loss).

    Example: with daily returns and ``confidence=0.95``, the return is the loss
    that the worst ~5% of days breach.
    """
    return -_tail(returns, confidence)[-1]


def conditional_value_at_risk(returns: Sequence[float], confidence: float = 0.95) -> float:
    """Historical CVaR / expected shortfall — the *average* loss in the tail beyond
    :func:`value_at_risk` (positive = loss). Always ``>= value_at_risk``."""
    tail = _tail(returns, confidence)
    return -sum(tail) / len(tail)
