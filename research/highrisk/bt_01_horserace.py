"""bt_01: HORSE RACE — A0..A3 under QR-parity accounting (daily-close execution).

  A0 = TG1x-hyst2 baseline
  A1 = A0 + VB(10,100,5)   (primary overlay)
  A2 = A0 + TS(30)         (fallback overlay)
  A3 = A0 + VB x TS        (multiplicative)

Also verifies overlay state machines reproduce the algo-strategist's traces
(algo_volbreaker_episodes.csv: 17 eps / 233 days off; algo_ts_trace tau=30 fires
2021-05-17 + 2021-12-10 per STRATEGY_SPEC_v1.md section 5).

Outputs: bt_horserace.csv (metrics per arm x window),
         bt_daily.csv (daily series for all downstream scripts),
         bt_trace_check.json (overlay trace verification).
"""
import pandas as pd, numpy as np, json, sys
sys.path.insert(0, "research/highrisk")
from bt_common import (OUT, TC, WINDOWS, build_panel, gate_hyst, vb_multiplier,
                       ts_multiplier, sim, arm_metrics)

d = build_panel()
idx = d.index
r = d["ret1"].values
fund = d["fund_sum"].values
close = d["close"].values
sma200 = d["sma200"].values
rv10 = d["rv10"].values

gate = gate_hyst(close, sma200)

# ---------- overlay trace verification vs algo-strategist artifacts ----------
check = {}
m_vb, vb_eps = vb_multiplier(rv10, 1.00, 5)
avb = pd.read_csv(f"{OUT}/algo_volbreaker_episodes.csv")
# their episode trigger_date t means rv10[t]>X -> decided OFF at t (our space, same date)
my_trig = [str(idx[e["trigger_i"]].date()) for e in vb_eps]
my_rearm = [str(idx[e["rearm_i"]].date()) if e["rearm_i"] is not None else "open" for e in vb_eps]
check["vb_X100_k5"] = {
    "my_triggers": my_trig, "my_rearms": my_rearm,
    "algo_triggers": avb["trigger_date"].tolist(), "algo_rearms": avb["rearm_date"].tolist(),
    "triggers_match": my_trig == avb["trigger_date"].tolist(),
    "rearms_match": my_rearm == avb["rearm_date"].tolist(),
    "my_days_off_decided_space": int((m_vb == 0).sum()),  # expect 233 (= their m==0 count)
    "algo_days_off": 233,
}
# sensitivity counts from algo_dd_diag.json
dd = json.load(open(f"{OUT}/algo_dd_diag.json"))
for X, lbl in [(0.80, "X80"), (0.90, "X90"), (1.10, "X110"), (1.20, "X120")]:
    mx, ex = vb_multiplier(rv10, X, 5)
    check[f"vb_{lbl}_k5"] = {"my_days_off": int((mx == 0).sum()),
                             "algo_days_off": dd["volbreaker_sensitivity"][lbl]["days_off"],
                             "my_n_episodes": len(ex),
                             "algo_n_episodes": dd["volbreaker_sensitivity"][lbl]["n_episodes"]}

m_ts, ts_eps = ts_multiplier(close, gate, 0.30)
check["ts_tau30"] = {
    "my_fires": [{"fire_date": str(idx[e["fire_i"]].date()), "close": round(e["close"], 0),
                  "rearm": str(idx[e["rearm_i"]].date()) if e["rearm_i"] is not None else "open"}
                 for e in ts_eps],
    "spec_expected_fires": ["2021-05-17 @ ~43.6k", "2021-12-10"],
    "my_blocked_gate_on_days": int(((m_ts == 0) & (gate == 1)).sum()),
    "spec_expected_blocked": 21,
}
# tau=25 trace must reproduce algo_ts_episodes.csv
m_ts25, ts25_eps = ts_multiplier(close, gate, 0.25)
ats = pd.read_csv(f"{OUT}/algo_ts_episodes.csv")
check["ts_tau25"] = {
    "my_fires": [{"fire_date": str(idx[e["fire_i"]].date()), "close": round(e["close"], 0),
                  "rearm": str(idx[e["rearm_i"]].date()) if e["rearm_i"] is not None else "open"}
                 for e in ts25_eps],
    "algo_fires": ats.to_dict("records"),
}

# ---------- arms ----------
arms = {
    "A0_baseline": gate,
    "A1_VB": gate * m_vb,
    "A2_TS30": gate * m_ts,
    "A3_VB_TS": gate * m_vb * m_ts,
}

rows = []
daily = pd.DataFrame({"close": close, "ret_btc": r, "fund_sum": fund, "sma200": sma200,
                      "rv10": rv10, "gate": gate, "m_vb": m_vb, "m_ts30": m_ts}, index=idx)
for name, w in arms.items():
    rets, wh, turn = sim(w, r, fund)
    daily[f"w_{name}"] = wh
    daily[f"ret_{name}"] = rets
    daily[f"turn_{name}"] = turn
    for lbl, a, b, skip in WINDOWS:
        ps = arm_metrics(rets, wh, turn, fund, gate, idx, lbl, a, b, skip)
        ps["arm"] = name
        rows.append(ps)

hr = pd.DataFrame(rows)
cols = ["arm", "window", "n", "cagr", "sharpe", "ann_vol", "mdd", "total_x",
        "ann_ret_arith", "round_trips", "round_trips_per_yr", "n_trades", "turnover_ann",
        "cost_drag_ann_pct", "funding_drag_ann_pct", "avg_w",
        "gate_on_days", "blocked_gate_on_days", "pct_gate_on_blocked"]
hr = hr[cols]
for c in ["cagr", "sharpe", "ann_vol", "mdd", "ann_ret_arith", "total_x", "round_trips_per_yr",
          "turnover_ann", "cost_drag_ann_pct", "funding_drag_ann_pct", "avg_w",
          "pct_gate_on_blocked"]:
    hr[c] = hr[c].astype(float).round(4)
hr.to_csv(f"{OUT}/bt_horserace.csv", index=False)
daily.to_csv(f"{OUT}/bt_daily.csv", float_format="%.10f")
with open(f"{OUT}/bt_trace_check.json", "w") as fh:
    json.dump(check, fh, indent=2, default=str)

print(json.dumps(check, indent=2, default=str))
print("\n=== HORSE RACE (QR-parity, net) ===")
print(hr.to_string(index=False))
