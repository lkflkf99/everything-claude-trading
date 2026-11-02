"""algo_ts_trace: trigger trace for the FALLBACK overlay — trailing stop from
cycle peak while gated in (state machine only, NOT a backtest).

Rule traced: while gate==1, peak = max(close) since last 0->1 transition;
fire when close(t) < (1-tau)*peak -> m=0 from next day; re-arm at next gate 0->1.

Outputs: algo_ts_episodes.csv + printed summary.
"""
import pandas as pd, numpy as np

OUT = "research/highrisk"
d = pd.read_csv(f"{OUT}/qr_final_daily.csv", index_col=0, parse_dates=True)
close = d["close"].values
gate = d["gate_hyst"].values
idx = d.index

def ts_trace(tau):
    m = np.ones(len(d)); state = 1; peak = -np.inf; eps = []
    for t in range(len(d)):
        m[t] = state
        c = close[t]
        if gate[t] == 1:
            if t > 0 and gate[t - 1] == 0:
                peak = c
                if state == 0:          # re-arm on fresh gate entry
                    state = 1
                    if eps and "rearm_date" not in eps[-1]:
                        eps[-1]["rearm_date"] = str(idx[t].date())
            peak = max(peak, c)
            if state == 1 and c < (1 - tau) * peak:
                state = 0
                eps.append({"fire_date": str(idx[t].date()), "close": round(float(c), 0),
                            "cycle_peak": round(float(peak), 0),
                            "dd_from_peak_pct": round(100 * (c / peak - 1), 1)})
        # gate==0: peak reference frozen; stop state persists until next gate entry
    for e in eps:
        if "rearm_date" not in e:
            e["rearm_date"] = "open"
    return m, eps

rows = {}
for tau in [0.20, 0.25, 0.30]:
    m, eps = ts_trace(tau)
    rows[f"tau{int(tau*100)}"] = {"n_fires": len(eps),
                                  "days_blocked": int(((m == 0) & (gate == 1)).sum()),
                                  "fires": eps}
    if tau == 0.25:
        pd.DataFrame(eps).to_csv(f"{OUT}/algo_ts_episodes.csv", index=False)

for k, v in rows.items():
    print(k, "fires:", v["n_fires"], "blocked_gate_on_days:", v["days_blocked"])
    for e in v["fires"]:
        print("   ", e)
