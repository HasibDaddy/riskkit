"""Tests for riskkit.correlation.CorrelationGuard."""
import pytest

from riskkit import CorrelationGuard


def test_static_group_blocks_second_position():
    guard = CorrelationGuard(static_groups={"majors": {"BTC", "ETH"}})
    d = guard.can_open("ETH", open_symbols={"BTC"})
    assert not d.allowed
    assert d.blocking_symbol == "BTC"
    assert d.group == "majors"


def test_unrelated_symbol_allowed():
    guard = CorrelationGuard(static_groups={"majors": {"BTC", "ETH"}})
    assert guard.can_open("XRP", open_symbols={"BTC"}).allowed
    assert guard.can_open("BTC", open_symbols=set()).allowed


def test_dynamic_grouping_from_correlation():
    pd = pytest.importorskip("pandas")
    idx = pd.date_range("2026-01-01", periods=40, freq="D")
    a = pd.Series(range(1, 41), index=idx, dtype=float)
    closes = {
        "A": a,
        "B": a * 2.0,                       # perfectly correlated with A
        "FLAT": pd.Series([100.0] * 40, index=idx),  # no variance -> ignored
    }
    guard = CorrelationGuard(dynamic_threshold=0.75)
    guard.recompute_dynamic(closes)

    assert not guard.can_open("B", open_symbols={"A"}).allowed
    assert guard.can_open("FLAT", open_symbols={"A"}).allowed
