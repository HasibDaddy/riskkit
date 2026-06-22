"""Tests for riskkit.metrics — historical VaR and CVaR."""
import pytest

from riskkit import conditional_value_at_risk, value_at_risk


def test_var_is_the_tail_threshold_loss():
    # 10 returns, 80% confidence -> worst 2 = [-0.10, -0.05]; VaR threshold = 0.05.
    returns = [-0.10, -0.05, -0.02, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    assert value_at_risk(returns, confidence=0.8) == pytest.approx(0.05)


def test_cvar_is_the_mean_tail_loss():
    returns = [-0.10, -0.05, -0.02, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    # mean of worst 2 = -0.075 -> CVaR 0.075
    assert conditional_value_at_risk(returns, confidence=0.8) == pytest.approx(0.075)


def test_cvar_never_below_var():
    returns = [-0.10, -0.05, -0.02, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    for conf in (0.9, 0.95, 0.99):
        assert conditional_value_at_risk(returns, conf) >= value_at_risk(returns, conf)


def test_empty_and_bad_confidence_raise():
    with pytest.raises(ValueError):
        value_at_risk([], 0.95)
    with pytest.raises(ValueError):
        value_at_risk([0.01, -0.02], confidence=1.5)


# Property: CVaR (mean tail loss) is always >= VaR (threshold loss).
hyp = pytest.importorskip("hypothesis")
from hypothesis import given, settings
from hypothesis import strategies as st

_returns = st.lists(
    st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    min_size=1, max_size=200,
)


@given(returns=_returns, confidence=st.floats(min_value=0.5, max_value=0.999))
@settings(max_examples=200)
def test_cvar_ge_var_property(returns, confidence):
    assert conditional_value_at_risk(returns, confidence) >= value_at_risk(returns, confidence) - 1e-12
