"""qr_05: ONE pre-registered gate refinement — 2% hysteresis band (5th gate variant,
Bonferroni alpha = 0.05/5 = 0.01 for the gate-variant family).

Motivation identified AFTER seeing qr_04 (honest disclosure): 2021 whipsaw year
(26 round trips, 18 <=10d) bled ~-35% and funding drag. A hysteresis band only
reduces flips; it cannot create alpha. Test: does it dominate the plain gate on
net CAGR/MDD in BOTH the 2021 stress year and the 2022-2026 OOS window?

  HYST2%: state=1 while close > 1.02*SMA200 (enter), stays 1 until close < 0.98*SMA200 (exit).
          Between bands: keep previous state (start 0).

Outputs: qr_hysteresis.csv, qr_hysteresis_verdict.json
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

gate_plain = (close > sma200).astype(float)

# hysteresis state machine
hyst = np.zeros(len(close))
state = 0.0
for t in range(len(close)):
    if np.isnan(sma200[t]):
        hyst[t] = 0.0
        continue
    if state == 0.0 and close[t] > 1.02 * sma200[t]:
        state = 1.0
    elif state == 1.0 and close[t] < 0.98 * sma200[t]:
        state = 0.0
    hyst[t] = state

def sim(w_target):
    w = np.nan_to_num(np.asarray(w_target, float), nan=0.0)
    wh = np.concatenate([[0.0], w[:-1]])
    rets = np.zeros(len(w)); turn = np.zeros(len(w))
    for t in range(len(w)):
        turn[t] = abs(w[t] - wh[t] * (1 + r[t]))
        rets[t] = wh[t] * r[t] - wh[t] * fund[t] - TC * turn[t]
    return rets, wh, turn

def trips(w, start=200):
    g = w[start:]
    cross = np.diff(np.concatenate([[0.0], g]))
    return int((cross == 1).sum()), int((cross == -1).sum())

rows = []
for name, w in [("TG1x_plain", gate_plain), ("TG1x_hyst2", hyst)]:
    rets, wh, turn = sim(w)
    for lbl, a, b in [("FULL_2020H2_2026", "2020-01-01", "2026-10-31"),
                      ("Y2021", "2021-01-01", "2021-12-31"),
                      ("OOS_2022_2026", "2022-01-01", "2026-10-31"),
                      ("Y2023", "2023-01-01", "2023-12-31"),
                      ("Y2024", "2024-01-01", "2024-12-31"),
                      ("Y2025_2026", "2025-01-01", "2026-10-31")]:
        m = (idx >= a) & (idx <= b)
        if lbl.startswith("FULL"):
            mm = np.zeros(len(idx), bool); mm[200:] = True
            m = m & mm
        ps = perf_stats(rets[m])
        en, ex = trips(w)
        ps.update({"window": lbl, "strategy": name, "entries_total": en,
                   "pct_days_in_market": round(100 * float((wh[m] > 0).mean()), 1),
                   "funding_drag_ann_pct": round(100 * float((wh[m] * fund[m]).mean() * 365), 2)})
        rows.append(ps)
pf = pd.DataFrame(rows)
for c in ["ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd"]:
    pf[c] = pf[c].astype(float).round(3)
pf.to_csv(f"{OUT}/qr_hysteresis.csv", index=False)
print("=== HYSTERESIS vs PLAIN GATE (net) ===")
print(pf[["window", "strategy", "n", "ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd",
          "pct_days_in_market", "funding_drag_ann_pct"]].to_string(index=False))

en_p, _ = trips(gate_plain); en_h, _ = trips(hyst)
print(f"\nround trips: plain={en_p}, hyst2%={en_h}")

verdict = {"variant": "TG1x_hyst2 (2% band, 5th gate variant, Bonferroni alpha 0.01)",
           "round_trips_plain": en_p, "round_trips_hyst": en_h}
with open(f"{OUT}/qr_hysteresis_verdict.json", "w") as fh:
    json.dump(verdict, fh, indent=2)
