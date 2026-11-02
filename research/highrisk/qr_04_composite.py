"""qr_04: FROZEN COMPOSITE SPEC + expected performance with honest uncertainty.

Survivors after qr_01..qr_03: the 200d trend gate on a long perp (crash-insurance
overlay on positive drift). Funding tilt DEAD (OOS wrong sign). Taker flow DEAD.
Vol scaling adds nothing over the gate (paired p=0.76) -> two frozen sizing variants:

  COMPOSITE A (primary, simplest): TG1x
    w(t) = 1  if close(t-1) > SMA200(t-1) = mean(close(t-201..t-1)), else 0.
  COMPOSITE B (vol-managed alternative): VT_TG
    w(t) = min(2.0, 0.50 / (std(ret1, 30d, t-1) * sqrt(365))) * 1[close(t-1) > SMA200(t-1)]

Both: perp, daily rebalance at 00:00 UTC, taker 5bp/side on |delta notional|,
funding paid/received daily at w_held. No fitted parameters anywhere.

Outputs: qr_composite_daily.csv, qr_composite_perf.csv, qr_composite_spec.json,
         qr_whipsaw.csv, qr_composite_forward.json
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
gate = (close > sma200).astype(float)
rv30 = (d["ret1"].rolling(30).std() * np.sqrt(365)).values
VT = np.clip(0.50 / rv30, 0, 2.0)

def sim(w_target):
    w = np.nan_to_num(np.asarray(w_target, float), nan=0.0)
    wh = np.concatenate([[0.0], w[:-1]])
    rets = np.zeros(len(w)); turn = np.zeros(len(w)); fund_paid = np.zeros(len(w))
    for t in range(len(w)):
        drifted = wh[t] * (1 + r[t])
        turn[t] = abs(w[t] - drifted)
        fund_paid[t] = wh[t] * fund[t]
        rets[t] = wh[t] * r[t] - fund_paid[t] - TC * turn[t]
    return rets, wh, turn, fund_paid

res = {}
for name, w in [("TG1x", gate), ("VT_TG", VT * gate)]:
    rets, wh, turn, fp = sim(w)
    res[name] = {"ret": rets, "w": wh, "turn": turn, "fund": fp}

df_out = pd.DataFrame({"close": close, "ret_btc": r, "gate": gate, "rv30": rv30,
                       "w_TG1x": res["TG1x"]["w"], "ret_TG1x": res["TG1x"]["ret"],
                       "w_VT_TG": res["VT_TG"]["w"], "ret_VT_TG": res["VT_TG"]["ret"]},
                      index=idx)
df_out.to_csv(f"{OUT}/qr_composite_daily.csv")

# ---------- performance: full (post-warmup), OOS, per-year ----------
WINDOWS = [("FULL_2020H2_2026", "2020-01-01", "2026-10-31", 200),
           ("OOS_2022_2026", "2022-01-01", "2026-10-31", 0)]
for y in range(2021, 2027):
    WINDOWS.append((f"Y{y}", f"{y}-01-01", f"{y}-12-31", 0))
rows = []
for lbl, a, b, skip in WINDOWS:
    m = (idx >= a) & (idx <= b)
    if skip:
        mm = np.zeros(len(idx), bool); mm[skip:] = True
        m = m & mm
    for name in res:
        rr = res[name]["ret"][m]
        ps = perf_stats(rr)
        ps.update({"window": lbl, "strategy": name,
                   "avg_w": round(float(res[name]["w"][m].mean()), 3),
                   "turnover_peryr": round(float(res[name]["turn"][m].mean() * 365), 2),
                   "cost_drag_ann_pct": round(100 * float((res[name]["turn"][m] * TC).mean() * 365), 2),
                   "funding_drag_ann_pct": round(100 * float(res[name]["fund"][m].mean() * 365), 2),
                   "pct_days_in_market": round(100 * float((res[name]["w"][m] > 0).mean()), 1)})
        rows.append(ps)
pf = pd.DataFrame(rows)
for c in ["ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd"]:
    pf[c] = pf[c].astype(float).round(3)
pf.to_csv(f"{OUT}/qr_composite_perf.csv", index=False)
print("=== COMPOSITE PERFORMANCE (net) ===")
print(pf[["window", "strategy", "n", "ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd",
          "avg_w", "pct_days_in_market", "cost_drag_ann_pct", "funding_drag_ann_pct"]].to_string(index=False))

# ---------- whipsaw analysis of the gate ----------
g = gate[200:]
gidx = idx[200:]
cross = np.diff(np.concatenate([[0.0], g]))  # +1 enter, -1 exit
entries = np.where(cross == 1)[0]
exits = np.where(cross == -1)[0]
ep = pd.DataFrame({"date": gidx[entries], "type": "entry"})
xp = pd.DataFrame({"date": gidx[exits], "type": "exit"})
ev = pd.concat([ep, xp]).sort_values("date")
# round trips
rt = []
open_d = None
for _, row in ev.iterrows():
    if row["type"] == "entry":
        open_d = row["date"]
    elif row["type"] == "exit" and open_d is not None:
        rt.append({"entry": open_d, "exit": row["date"],
                   "days": (row["date"] - open_d).days})
rtd = pd.DataFrame(rt)
if len(rtd):
    rtd["ret_during"] = [round(100 * float((close[idx.get_loc(e)] / close[idx.get_loc(s)] - 1)), 1)
                         for s, e in zip(rtd["entry"], rtd["exit"])]
    short = rtd[rtd["days"] <= 10]
    ws = {"n_round_trips": len(rtd), "median_days_in": float(rtd["days"].median()),
          "n_whipsaws_le10d": len(short), "whipsaw_cost_est_pct_total":
              round(100 * float(len(rtd) * 2 * TC), 1),
          "mean_ret_per_episode_pct": round(float(rtd["ret_during"].mean()), 1)}
    rtd.to_csv(f"{OUT}/qr_whipsaw.csv", index=False)
print("\n=== GATE ROUND TRIPS ==="); print(ws)
print(rtd.to_string(index=False))

# ---------- forward expectation (honest) ----------
boot = json.load(open(f"{OUT}/qr_bootstrap_oos.json"))
fwd = {
  "basis": "OOS 2022-2026 (1764d) net of costs+funding; 60d block bootstrap x2000",
  "TG1x": {
    "point": {"cagr": 0.219, "sharpe": 0.757, "mdd_realized": -0.325, "ann_vol": 0.334},
    "bootstrap": boot["bootstrap"]["TG1x"],
  },
  "VT_TG": {
    "point": {"cagr": 0.208, "sharpe": 0.672, "mdd_realized": -0.335, "ann_vol": 0.398},
    "bootstrap": boot["bootstrap"]["VT_TG"],
  },
  "regime_conditioning": {
    "note": "Gate edge = crash insurance. In windows WITH a >50pct BTC bear (2022), gate adds ~60pp/yr; in bull windows (2023-24) it COSTS ~30-100pp/yr of upside; in chop (2025-26) roughly neutral-to-slightly-positive.",
    "per_year_cagr_TG1x": "see qr_composite_perf.csv",
  },
  "multiple_testing_ledger": {
    "variants_evaluated_this_study": ["funding deciles x2 horizons", "fund_z regression x2 horizons x3 periods",
        "tilt regression", "4 strategies x 5 windows", "vt grid 40/50/60", "4 gate variants", "taker imb regression + OOS R2"],
    "selection_statement": "Primary gate (SMA200) chosen a priori; alternates reported, not selected. No parameter was optimized on returns. Nevertheless the gate's incremental value is only ~p=0.14-0.25 vs no-gate: treat the effect as economically-motivated insurance, not a high-t alpha.",
    "prior_pipeline_failures": ["4h breakout (anti-predictive)", "5 trend families OOS collapse", "fade-extremes IS fail"],
    "relation_to_prior_trend_failures": "Prior #2 used trend as RETURN signal at 4h/daily. Here trend is a 0/1 RISK GATE on unconditional long drift; it never predicts up-moves, it only refuses to hold below the 200d. Different mechanism; still, evidence base is ~2 bears (2022 full avoidance, 2025-26 partial)."
  }
}
with open(f"{OUT}/qr_composite_forward.json", "w") as fh:
    json.dump(fwd, fh, indent=2)
print("\n=== FORWARD (see qr_composite_forward.json) ===")
print(json.dumps({k: fwd[k] for k in ["TG1x", "VT_TG"]}, indent=2))

spec = {
  "name": "BTC perp 200d-gated long (TG1x) / vol-targeted variant (VT_TG)",
  "universe": "Binance USDT-margined BTCUSDT perpetual",
  "signal": {
    "close": "daily close UTC of perp",
    "sma200": "SMA200(t) = mean(close[t-199..t]) of daily closes",
    "gate(t)": "1 if close(t) > sma200(t) else 0",
    "rv30(t)": "std(daily simple returns t-29..t) * sqrt(365)",
    "vol_scale(t)": "min(2.0, 0.50 / rv30(t))"
  },
  "position": {
    "TG1x": "w(t+1) = gate(t)",
    "VT_TG": "w(t+1) = min(2.0, vol_scale(t) * gate(t))  [cap binds first: never > 2x]",
    "rebalance": "daily at 00:00 UTC (trade at close of day t = open of day t+1)"
  },
  "costs_funding": {
    "taker_fee": "5bp per side on |change in notional weight| (incl. drift rebalance)",
    "funding": "w * sum(8h funding rates that day); long pays when positive, receives when negative",
    "expected_funding_drag": "TG1x: only in-market ~50-60% of days; drag = avg_w * ann funding (~5.7%/yr OOS for VT_TG, ~similar for TG1x when in-market)"
  },
  "frozen_params": {"sma_window": 200, "vol_target": 0.50, "vol_window": 30, "lev_cap": 2.0},
  "no_other_overlays": "funding tilt and taker-flow overlay tested and REJECTED (see qr_funding_*, qr_taker_*)"
}
with open(f"{OUT}/qr_composite_spec.json", "w") as fh:
    json.dump(spec, fh, indent=2)
print("\nspec written to qr_composite_spec.json")
