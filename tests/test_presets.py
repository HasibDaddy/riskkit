"""Tests for RiskConfig presets and dict/YAML loading."""
import pytest

from riskkit import RiskConfig, RiskManager, TradeIntent

PRESETS = ["conservative", "balanced", "aggressive"]


def _intent():
    return TradeIntent(
        symbol="BTC/USDT", side="long",
        entry_price=100, stop_price=98, target_price=106,  # R:R = 3.0
        score=82, atr=2, atr_baseline=2,
    )


@pytest.mark.parametrize("name", PRESETS)
def test_preset_builds_working_manager(name):
    rm = RiskManager(RiskConfig.preset(name))
    rm.on_equity(10_000)
    decision = rm.evaluate(_intent())
    assert decision.ok
    assert decision.units > 0


def test_presets_ordered_by_risk_appetite():
    c, b, a = (RiskConfig.preset(n) for n in PRESETS)
    # Risk-on knobs increase from conservative → aggressive…
    assert c.base_risk_pct < b.base_risk_pct < a.base_risk_pct
    assert c.max_notional_pct < b.max_notional_pct < a.max_notional_pct
    assert c.max_concurrent < b.max_concurrent < a.max_concurrent
    assert c.drawdown["halt_pct"] < b.drawdown["halt_pct"] < a.drawdown["halt_pct"]
    # …while the quality bars relax.
    assert c.validator["min_rr_ratio"] > b.validator["min_rr_ratio"] > a.validator["min_rr_ratio"]
    assert c.validator["min_score"] > b.validator["min_score"] > a.validator["min_score"]


def test_preset_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown preset"):
        RiskConfig.preset("yolo")


def test_from_dict_round_trips():
    cfg = RiskConfig.aggressive()
    assert RiskConfig.from_dict(cfg.to_dict()) == cfg


def test_from_dict_rejects_unknown_field():
    with pytest.raises(ValueError, match="unknown RiskConfig fields"):
        RiskConfig.from_dict({"base_risk_pct": 1.0, "typo": 5})


def test_from_dict_rejects_non_mapping_component():
    with pytest.raises(TypeError, match="must be a mapping"):
        RiskConfig.from_dict({"drawdown": 5})


def test_from_dict_partial_keeps_defaults():
    cfg = RiskConfig.from_dict({"base_risk_pct": 0.75, "drawdown": {"halt_pct": 9}})
    assert cfg.base_risk_pct == 0.75
    assert cfg.drawdown == {"halt_pct": 9}
    assert cfg.max_notional_pct == 4.0          # untouched default


def test_from_yaml_round_trips(tmp_path):
    yaml = pytest.importorskip("yaml")
    path = tmp_path / "risk.yaml"
    path.write_text(yaml.safe_dump(RiskConfig.balanced().to_dict()))
    assert RiskConfig.from_yaml(str(path)) == RiskConfig.balanced()
