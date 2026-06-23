"""Multi-asset example: allocate, vol-target, and vet a cross-sector book.

Run it:  python examples/multi_asset_book.py

Brings the v0.4 pieces together on a small book. Two halves, because they answer
two different questions:

  A. *How much of each?* — the standalone, composable sizers:
       inverse_vol_weights   — split a budget across a basket by 1/sigma, so every
                               name contributes equal risk (naive risk parity).
       volatility_target_size — size each leg to a target volatility, so a calm
                               name takes a bigger position than a wild one.
       kelly_fraction        — the edge-optimal risk fraction (half-Kelly here).

  B. *May I actually open it?* — the RiskManager façade enforcing portfolio
     caps as the book fills: a per-sector exposure cap stops one sector from
     dominating, and a heat cap bounds total risk-at-stop.

Nothing here touches an exchange — you feed in numbers your own system already
has (prices, volatilities, signal scores) and get back auditable decisions.
"""
from datetime import datetime, timezone

from riskkit import (
    RiskConfig,
    RiskManager,
    TradeIntent,
    inverse_vol_weights,
    kelly_fraction,
    volatility_target_size,
)

EQUITY = 100_000.0

# symbol -> (sector, price, daily return-volatility)
BASKET = {
    "BTC/USDT": ("crypto", 60_000.0, 0.040),
    "ETH/USDT": ("crypto",  3_000.0, 0.050),
    "AAPL":     ("tech",       190.0, 0.018),
    "MSFT":     ("tech",       420.0, 0.016),
    "XOM":      ("energy",     110.0, 0.022),
}

# ── A. Allocation & sizing with the standalone sizers ──────────────────────
print("A. standalone sizers\n")

vols = {sym: vol for sym, (_, _, vol) in BASKET.items()}
weights = inverse_vol_weights(vols)
print("  inverse-vol weights (risk parity, sum=1.0):")
for sym, w in sorted(weights.items(), key=lambda kv: -kv[1]):
    print(f"    {sym:<10} {w:6.1%}   (vol {vols[sym]:.1%})")

TARGET_VOL_PCT = 0.5   # want each leg to carry ~0.5% of equity in daily vol
print(f"\n  volatility-targeted sizes (target {TARGET_VOL_PCT}% equity vol per leg):")
for sym, (_, price, vol) in BASKET.items():
    units = volatility_target_size(EQUITY, price, vol, TARGET_VOL_PCT, max_notional_pct=40)
    dollar_vol = units * price * vol            # ≈ 0.5% of equity for every leg
    print(f"    {sym:<10} {units:12.4f} units   daily vol ${dollar_vol:8,.0f} "
          f"({dollar_vol / EQUITY:.2%} of equity)")

hk = kelly_fraction(win_rate=0.52, avg_win=1.1, avg_loss=1.0, fraction=0.5)
print(f"\n  half-Kelly for a 52% / 1.1R edge: risk {hk:.1%} of equity per bet")

# ── B. Vetting the book through portfolio caps ─────────────────────────────
print("\nB. RiskManager — portfolio caps as the book fills\n")

risk = RiskManager(RiskConfig(
    base_risk_pct=1.0,
    max_notional_pct=10.0,              # each leg caps at 10% of equity
    max_exposure_per_sector_pct=15.0,   # ...and no single sector above 15%
    max_portfolio_heat_pct=5.0,         # bound total risk-at-stop
    # Leave total-exposure headroom so the *sector* cap is what bites here.
    validator=dict(min_score=70, min_rr_ratio=1.5, max_total_exposure_pct=40.0),
    session=dict(min_minutes_between_trades=0),
))
now = datetime(2026, 1, 1, tzinfo=timezone.utc)
risk.on_equity(EQUITY, now=now)

# Two tech names and one energy name. With a tight (2%) stop each leg fills at the
# 10% notional cap, so the second tech leg pushes 'tech' past the 15% sector cap.
candidates = [
    ("AAPL", "tech",   190.0),
    ("MSFT", "tech",   420.0),
    ("XOM",  "energy", 110.0),
]
for sym, sector, price in candidates:
    stop = price * 0.98              # 2% stop
    target = price + 3 * (price - stop)   # R:R = 3
    decision = risk.evaluate(TradeIntent(
        symbol=sym, side="long", sector=sector,
        entry_price=price, stop_price=stop, target_price=target, score=80,
    ), now=now)
    if decision.ok:
        risk.on_fill(decision)
        print(f"    {sym:<6} FILL   notional {decision.notional:>10,.0f}   "
              f"'{sector}' sector now {risk.sector_exposure_pct(sector):.1f}%")
    else:
        print(f"    {sym:<6} BLOCK  — {decision.reasons[0]}")

by_sector = ", ".join(f"{k} {v:.1f}%" for k, v in risk.sector_exposure().items())
print(f"\n  final book: exposure {risk.exposure_pct():.1f}%  |  "
      f"heat {risk.portfolio_heat_pct():.2f}%  |  by sector: {by_sector}")
