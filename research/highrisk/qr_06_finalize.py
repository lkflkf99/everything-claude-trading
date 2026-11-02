"""qr_06: Finalize frozen composite spec (post-hysteresis) + daily series for algo-strategist.

FINAL SPEC (primary): TG1x-hyst2
  state machine: flat -> long when close(t) > 1.02 * SMA200(t); long -> flat when
  close(t) < 0.98 * SMA200(t); otherwise keep prior state. SMA200 on daily UTC closes.
  w(t+1) = state(t)  (1x perp long or flat). Daily 00:00 UTC rebalance.
  Costs 5bp taker per side on |d weight|; funding paid/received at held weight.
Alternative (tested): VT_TG plain gate with vol target 50%, cap 2x.

Outputs: qr_final_spec.json, qr_final_daily.csv (both variants), qr_final_summary_stats.csv
"""
import pandas as pd, numpy as np, json, sys
sys.path.insert(0, "research/highrisk")
from qr_utils import perf_stats

OUT = "research/highrisk"
pan = pd.read_csv(f"{OUT}/qr_daily_panel.csv", index_col=0, parse_dates=True)
TC = 0.0005
d = pan.dropna(subset=["ret1", "fund_sum"]).copy()
r = d["ret1"].fillna(0.0).values
fund = d["fund_sum"].fillna(0.0).values
idx = d.index
close = d["close"].values
sma200 = d["close"].rolling(200).mean().values
rv30 = (d["ret1"].rolling(30).std() * np.sqrt(365)).values

gate_plain = (close > sma200).astype(float)
hyst = np.zeros(len(close)); state = 0.0
for t in range(len(close)):
    if np.isnan(sma200[t]):
        hyst[t] = 0.0; continue
    if state == 0.0 and close[t] > 1.02 * sma200[t]:
        state = 1.0
    elif state == 1.0 and close[t] < 0.98 * sma200[t]:
        state = 0.0
    hyst[t] = state
VT_TG = np.clip(0.50 / rv30, 0, 2.0) * gate_plain

def sim(w_target):
    w = np.nan_to_num(np.asarray(w_target, float), nan=0.0)
    wh = np.concatenate([[0.0], w[:-1]])
    rets = np.zeros(len(w)); turn = np.zeros(len(w))
    for t in range(len(w)):
        turn[t] = abs(w[t] - wh[t] * (1 + r[t]))
        rets[t] = wh[t] * r[t] - wh[t] * fund[t] - TC * turn[t]
    return rets, wh, turn

out = pd.DataFrame({"close": close, "ret_btc": r, "fund_sum": fund, "sma200": sma200,
                    "rv30": rv30, "gate_hyst": hyst, "gate_plain": gate_plain}, index=idx)
stats_rows = []
for name, w in [("TG1x_hyst2", hyst), ("VT_TG", VT_TG)]:
    rets, wh, turn = sim(w)
    out[f"w_{name}"] = wh
    out[f"ret_{name}"] = rets
    for lbl, a, b, skip in [("FULL_2020H2_2026", "2020-01-01", "2026-10-31", 200),
                            ("OOS_2022_2026", "2022-01-01", "2026-10-31", 0)]:
        m = (idx >= a) & (idx <= b)
        if skip:
            mm = np.zeros(len(idx), bool); mm[skip:] = True
            m = m & mm
        ps = perf_stats(rets[m])
        ps.update({"window": lbl, "strategy": name,
                   "avg_w": round(float(wh[m].mean()), 3),
                   "funding_drag_ann_pct": round(100 * float((wh[m] * fund[m]).mean() * 365), 2),
                   "cost_drag_ann_pct": round(100 * float((turn[m] * TC).mean() * 365), 2)})
        stats_rows.append(ps)
out.to_csv(f"{OUT}/qr_final_daily.csv")
sf = pd.DataFrame(stats_rows)
for c in ["ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd"]:
    sf[c] = sf[c].astype(float).round(3)
sf.to_csv(f"{OUT}/qr_final_summary_stats.csv", index=False)
print(sf.to_string(index=False))

spec = {
  "strategy_name": "TG1x-hyst2 — BTC perp 200d-SMA gated long with 2% hysteresis",
  "instrument": "Binance USDT-margined BTCUSDT perpetual (step 0.001 BTC)",
  "data_requirements": ["daily UTC close of perp", "8h funding rates (00/08/16 UTC)"],
  "definitions": {
    "close(t)": "daily close at 00:00 UTC (day boundary)",
    "SMA200(t)": "mean(close[t-199..t])",
    "upper_band(t)": "1.02 * SMA200(t)",
    "lower_band(t)": "0.98 * SMA200(t)",
    "state(t)": "1 if long, 0 if flat; transitions: 0->1 when close(t) > upper_band(t); 1->0 when close(t) < lower_band(t)"
  },
  "position_rule": "w(t+1) = state(t); execute at 00:00 UTC close of day t (day t+1 open); w in {0, 1}",
  "costs": {"taker": "0.05% per side on |delta w| (incl. drift rebalancing)",
            "funding": "w * sum of the day's 3 funding rates; paid by long when positive"},
  "frozen_parameters": {"sma_window_days": 200, "hysteresis_band_pct": 2.0,
                         "rebalance": "daily 00:00 UTC", "leverage": "1x (no leverage in primary)"},
  "alternative_tested_variant": {
    "VT_TG": "w(t+1) = min(2.0, 0.50/rv30(t)) * 1[close(t) > SMA200(t)]; full-sample Sharpe 0.821 vs 0.876 primary; OOS Sharpe 0.672 vs 0.754 primary; use only if risk-manager wants explicit vol scaling/leverage ceiling"},
  "rejected_overlays": {
    "funding_contrarian_tilt": "DEAD as price alpha: train NW t<=1.6, TEST wrong sign (7d: -0.59, 30d: -0.34), tilt regression OOS t=-0.34; mechanical carry benefit (+1.2-3.7%/yr) < churn cost + lost upside in composite (OOS CAGR 20.8% -> 15.6%)",
    "taker_flow_overlay": "DEAD: train t=1.74 with controls -> OOS t=0.42, OOS R2 = -0.7% to -1.9%, pred corr ~0. Coefficient collapsed 82% OOS."},
  "performance_expectation": "see qr_composite_forward.json and qr_final_summary_stats.csv",
  "known_failure_modes": [
    "whipsaw chop around SMA200 in high-funding regimes (2021: CAGR -20% even with hysteresis, -41% without; MDD -56%)",
    "slow exit: gate exits AFTER price already fell through the band (Apr-May 2021: rode -43% before exit)",
    "statistical fragility: gate's incremental value vs no-gate p ~ 0.14-0.25 (bootstrap); evidence base = ~2 bears",
    "funding regime: if funding flips persistently negative while gated ON, drag becomes benefit (2026: only 1.4-1.8%/yr drag); if 2021-like (30%/yr), in-market drag ~30%/yr at 1x"]
}
with open(f"{OUT}/qr_final_spec.json", "w") as fh:
    json.dump(spec, fh, indent=2)
print("\nwrote qr_final_spec.json and qr_final_daily.csv")
