"""bt_05: SENSITIVITY SURFACES (report-only; no re-selection).

VB grid: X in {80,90,100,110,120}% x k in {3,5,10}  (arm = gate x m_vb(X,k))
TS grid: tau in {20,25,30,35}%                       (arm = gate x m_ts(tau))
Windows: FULL_2020H2_2026 (skip 200) and OOS_2022_2026. QR-parity accounting.

Must reproduce: (i) documented flat VB surface (X=80..120 -> similar FULL MDD),
(ii) the tau=25 cliff (lockout 2021-01-27 -> 2021-08-09, misses 30k->63k leg).

Outputs: bt_sensitivity_vb.csv, bt_sensitivity_ts.csv, bt_sensitivity.json
"""
import pandas as pd, numpy as np, json, sys
sys.path.insert(0, "research/highrisk")
from bt_common import OUT, TC, build_panel, gate_hyst, vb_multiplier, ts_multiplier, sim
from qr_utils import perf_stats

d = build_panel()
idx = d.index
r = d["ret1"].values
fund = d["fund_sum"].values
close = d["close"].values
gate = gate_hyst(close, d["sma200"].values)
rv10 = d["rv10"].values

WINS = [("FULL_2020H2_2026", 200), ("OOS_2022_2026", 0)]
def wmask(skip, a, b):
    m = (idx >= a) & (idx <= b)
    if skip:
        mm = np.zeros(len(idx), bool); mm[skip:] = True
        m = m & mm
    return m

rows_vb = []
for X in [0.80, 0.90, 1.00, 1.10, 1.20]:
    for k in [3, 5, 10]:
        mvb, eps = vb_multiplier(rv10, X, k)
        rets, wh, turn = sim(gate * mvb, r, fund)
        row = {"X_pct": int(X * 100), "k": k, "n_episodes": len(eps),
               "days_off": int((mvb == 0).sum()),
               "blocked_gate_on_days": int(((mvb == 0) & (gate == 1)).sum())}
        for lbl, skip in WINS:
            m = wmask(skip, "2020-01-01" if skip else "2022-01-01", "2026-10-31")
            ps = perf_stats(rets[m])
            row[f"{lbl}_cagr"] = round(ps["cagr"], 4)
            row[f"{lbl}_sharpe"] = round(ps["sharpe"], 3)
            row[f"{lbl}_mdd"] = round(ps["mdd"], 4)
        rows_vb.append(row)
vb = pd.DataFrame(rows_vb)
vb.to_csv(f"{OUT}/bt_sensitivity_vb.csv", index=False)

rows_ts = []
for tau in [0.20, 0.25, 0.30, 0.35]:
    mts, eps = ts_multiplier(close, gate, tau)
    rets, wh, turn = sim(gate * mts, r, fund)
    fires = [{"fire": str(idx[e["fire_i"]].date()), "close": round(e["close"], 0),
              "rearm": str(idx[e["rearm_i"]].date()) if e["rearm_i"] is not None else "open"}
             for e in eps]
    row = {"tau_pct": int(tau * 100), "n_fires": len(eps),
           "blocked_gate_on_days": int(((mts == 0) & (gate == 1)).sum()),
           "fires": json.dumps(fires)}
    for lbl, skip in WINS:
        m = wmask(skip, "2020-01-01" if skip else "2022-01-01", "2026-10-31")
        ps = perf_stats(rets[m])
        row[f"{lbl}_cagr"] = round(ps["cagr"], 4)
        row[f"{lbl}_sharpe"] = round(ps["sharpe"], 3)
        row[f"{lbl}_mdd"] = round(ps["mdd"], 4)
    rows_ts.append(row)
ts = pd.DataFrame(rows_ts)
ts.to_csv(f"{OUT}/bt_sensitivity_ts.csv", index=False)

# flatness / cliff summary
full_mdd_span = float(vb["FULL_2020H2_2026_mdd"].max() - vb["FULL_2020H2_2026_mdd"].min())
full_cagr_span = float(vb["FULL_2020H2_2026_cagr"].max() - vb["FULL_2020H2_2026_cagr"].min())
ts25 = ts[ts["tau_pct"] == 25].iloc[0]
ts30 = ts[ts["tau_pct"] == 30].iloc[0]
summ = {
    "vb_surface_flatness": {
        "full_mdd_span_pp": round(100 * full_mdd_span, 2),
        "full_cagr_span_pp": round(100 * full_cagr_span, 2),
        "note": "flat surface reproduced iff span small across X=80..120 (all k)",
    },
    "ts_tau25_cliff": {
        "tau25_full_cagr": float(ts25["FULL_2020H2_2026_cagr"]),
        "tau30_full_cagr": float(ts30["FULL_2020H2_2026_cagr"]),
        "cliff_pp": round(100 * float(ts30["FULL_2020H2_2026_cagr"] - ts25["FULL_2020H2_2026_cagr"]), 2),
        "tau25_first_fire": json.loads(ts25["fires"])[0] if ts25["n_fires"] else None,
    },
}
with open(f"{OUT}/bt_sensitivity.json", "w") as fh:
    json.dump(summ, fh, indent=2)
print("=== VB surface (gate x VB(X,k)) ===")
print(vb.to_string(index=False))
print("\n=== TS surface (gate x TS(tau)) ===")
print(ts.drop(columns=["fires"]).to_string(index=False))
print("\n" + json.dumps(summ, indent=2))
