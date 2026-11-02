"""03: Drawdown anatomy — top drawdown episodes, crash moves, time underwater."""
import pandas as pd, numpy as np, json, os

OUT = "research/highrisk"

df = pd.read_csv("research/data/binance_um_btcusdt_perp_4h.csv", parse_dates=["open_time_utc"])
px = df.set_index("open_time_utc")["close"].astype(float).sort_index()

run_max = px.cummax()
dd = px / run_max - 1
underwater = dd < -1e-12

# split into episodes between new all-time-high (running-max) boundaries
episodes = []
in_ep = False
for t, v in dd.items():
    if not in_ep and v < -1e-12:
        in_ep = True; ep_start = t; ep_trough = t; ep_depth = v
    elif in_ep:
        if v < ep_depth:
            ep_depth = v; ep_trough = t
        if v >= -1e-12:  # recovered to new high
            episodes.append({"peak": ep_start, "trough": ep_trough, "recovery": t, "depth": ep_depth})
            in_ep = False
if in_ep:
    episodes.append({"peak": ep_start, "trough": ep_trough, "recovery": pd.NaT, "depth": ep_depth})

rows = []
for e in episodes:
    peak_px_date = px.loc[:e["peak"]][px.loc[:e["peak"]] == run_max.loc[e["peak"]]].index
    rows.append({
        "peak_date": str(e["peak"].date()), "trough_date": str(e["trough"].date()),
        "recovery_date": str(e["recovery"].date()) if pd.notna(e["recovery"]) else "unrecovered",
        "depth_pct": round(100 * float(e["depth"]), 1),
        "days_peak_to_trough": round((e["trough"] - e["peak"]).total_seconds() / 86400, 1),
        "days_underwater": round(((e["recovery"] if pd.notna(e["recovery"]) else px.index[-1]) - e["peak"]).total_seconds() / 86400, 1),
    })
eps = pd.DataFrame(rows).sort_values("depth_pct").reset_index(drop=True)
eps.to_csv(f"{OUT}/drawdown_episodes.csv", index=False)
top = eps.head(12)

# time underwater stats
pct_uw = 100 * float(underwater.mean())
cur_dd = float(dd.iloc[-1])

# worst 24h and 7d moves (crash anatomy)
r24 = px.pct_change(6)
r7d = px.pct_change(42)
worst24 = r24.nsmallest(10)
worst7d = r7d.nsmallest(10)
crash = {
    "worst_24h_moves": [{"date": str(t), "ret_pct": round(100 * float(v), 1)} for t, v in worst24.items()],
    "worst_7d_moves": [{"date": str(t), "ret_pct": round(100 * float(v), 1)} for t, v in worst7d.items()],
    "pct_time_underwater": round(pct_uw, 1),
    "current_dd_pct": round(100 * cur_dd, 1),
    "n_episodes_gt10pct": int((eps["depth_pct"] <= -10).sum()),
    "n_episodes_gt20pct": int((eps["depth_pct"] <= -20).sum()),
    "median_days_underwater_all": float(eps["days_underwater"].median()),
}
with open(f"{OUT}/drawdown_summary.json", "w") as fh:
    json.dump(crash, fh, indent=2)

# drawdown depth distribution (for sizing against 40-50% tolerance)
dd_depths = eps["depth_pct"]
depth_dist = {"p50": float(dd_depths.median()), "p90": float(dd_depths.quantile(0.9)),
              "min": float(dd_depths.min()), "n_episodes": int(len(eps))}
with open(f"{OUT}/drawdown_depth_distribution.json", "w") as fh:
    json.dump(depth_dist, fh, indent=2)

print("=== TOP 12 DRAWDOWN EPISODES ==="); print(top.to_string(index=False))
print("\n=== SUMMARY ==="); print(json.dumps(crash, indent=2))
print("\n=== DEPTH DIST ==="); print(json.dumps(depth_dist, indent=2))
