"""bt_04: 2021 EPISODE DETAIL — daily equity Apr-Dec 2021 per arm (QR-parity).

Per arm: equity normalized to 1.0 at 2021-04-01, trough (date/depth vs running
peak incl. pre-Apr history), key exit/re-entry events with dates and prices,
year-end equity. Daily series exported for risk-manager inspection.

Outputs: bt_episode2021_daily.csv, bt_episode2021.json
"""
import pandas as pd, numpy as np, json, sys
sys.path.insert(0, "research/highrisk")
from bt_common import OUT

daily = pd.read_csv(f"{OUT}/bt_daily.csv", index_col=0, parse_dates=True)
idx = daily.index
ARMS = ["A0_baseline", "A1_VB", "A2_TS30", "A3_VB_TS"]

eq = pd.DataFrame(index=idx)
for a in ARMS:
    eq[a] = np.cumprod(1.0 + daily[f"ret_{a}"].values)

seg = slice("2021-04-01", "2021-12-31")
ep = eq.loc[seg].copy()
ep["close"] = daily["close"].loc[seg]
ep["gate"] = daily["gate"].loc[seg]
ep["m_vb"] = daily["m_vb"].loc[seg]
ep["m_ts30"] = daily["m_ts30"].loc[seg]
ep["rv10"] = daily["rv10"].loc[seg]
for a in ARMS:
    ep[f"{a}_norm"] = ep[a] / ep[a].iloc[0]
ep.to_csv(f"{OUT}/bt_episode2021_daily.csv", float_format="%.8f")

out = {"normalization": "equity=1.0 at 2021-04-01; depth measured vs running peak (full history)",
       "arms": {}}
for a in ARMS:
    e = eq[a]
    pk = np.maximum.accumulate(e.values)
    dd = e.values / pk - 1.0
    m = (idx >= "2021-04-01") & (idx <= "2021-12-31")
    dd_seg = dd[m]
    e_seg = e[m]
    i_tr = int(np.argmin(dd_seg))
    seg_idx = idx[m]
    # weight-change events inside the window
    wh = daily[f"w_{a}"].values
    events = []
    prev = wh[0]
    for t in range(1, len(idx)):
        if wh[t] != prev and idx[t - 1] >= pd.Timestamp("2021-03-25") and idx[t] <= pd.Timestamp("2021-12-31"):
            events.append({"effective_date": str(idx[t].date()),
                           "from_decision_close_of": str(idx[t - 1].date()),
                           "decision_close": round(float(daily['close'].values[t - 1]), 0),
                           "w_new": float(wh[t])})
        prev = wh[t]
    out["arms"][a] = {
        "equity_2021_04_01": round(float(e_seg.iloc[0]), 4),
        "equity_2021_12_31": round(float(e_seg.iloc[-1]), 4),
        "ret_apr_dec_pct": round(100 * float(e_seg.iloc[-1] / e_seg.iloc[0] - 1), 2),
        "window_trough_date": str(seg_idx[i_tr].date()),
        "window_trough_dd_vs_running_peak_pct": round(100 * float(dd_seg[i_tr]), 2),
        "weight_events": events,
    }

# reference: A0 gate exit price (spec: 2021-05-19 @ 36.7k)
m19 = idx == pd.Timestamp("2021-05-19")
out["reference_A0_gate_exit"] = {
    "signal_close_date": "2021-05-19",
    "close": round(float(daily["close"].values[m19][0]), 0),
    "rv10_trigger_date_A1": "2021-05-12",
    "close_0512": round(float(daily["close"].values[idx == pd.Timestamp("2021-05-12")][0]), 0),
    "ts30_fire_date_A2": "2021-05-17",
    "close_0517": round(float(daily["close"].values[idx == pd.Timestamp("2021-05-17")][0]), 0),
}
with open(f"{OUT}/bt_episode2021.json", "w") as fh:
    json.dump(out, fh, indent=2)
print(json.dumps(out, indent=2))
