"""01: BTC perp market structure — overview, yearly stats, vol regimes, trend regimes."""
import pandas as pd, numpy as np, json, os

OUT = "research/highrisk"
os.makedirs(OUT, exist_ok=True)
BPY = 6 * 365  # 4h bars per year

df = pd.read_csv("research/data/binance_um_btcusdt_perp_4h.csv", parse_dates=["open_time_utc"])
df = df.set_index("open_time_utc").sort_index()
px = df["close"].astype(float)
ret4h = px.pct_change()

dclose = px.resample("1D").last().dropna()
dret = dclose.pct_change().dropna()

span_days = (px.index[-1] - px.index[0]).days
overview = {
    "span_start": str(px.index[0]), "span_end": str(px.index[-1]),
    "n_4h_bars": int(len(px)), "n_days": int(len(dclose)),
    "price_first": float(px.iloc[0]), "price_last": float(px.iloc[-1]),
    "total_return_x": round(float(px.iloc[-1] / px.iloc[0]), 2),
    "cagr_pct": round(100 * ((px.iloc[-1] / px.iloc[0]) ** (365.0 / span_days) - 1), 1),
    "ann_vol_4h_pct": round(100 * float(ret4h.std() * np.sqrt(BPY)), 1),
    "ann_vol_daily_pct": round(100 * float(dret.std() * np.sqrt(365)), 1),
    "daily_ret_mean_bp": round(1e4 * float(dret.mean()), 2),
    "daily_ret_std_pct": round(100 * float(dret.std()), 2),
    "daily_sharpe_rf0": round(float(dret.mean() / dret.std() * np.sqrt(365)), 2),
    "daily_skew": round(float(dret.skew()), 2),
    "daily_kurtosis_excess": round(float(dret.kurtosis()), 1),
    "pct_up_days": round(100 * float((dret > 0).mean()), 1),
}
with open(f"{OUT}/overview.json", "w") as fh:
    json.dump(overview, fh, indent=2)

# ---------- yearly stats ----------
rows = []
for y in sorted(set(dclose.index.year)):
    m = dclose.index.year == y
    dc = dclose[m]; dr = dret[dret.index.year == y]
    p4 = px[px.index.year == y]
    if len(dc) < 30:
        continue
    run_max = p4.cummax()
    dd = (p4 / run_max - 1).min()
    rows.append({
        "year": y, "n_days": len(dc),
        "start": round(float(dc.iloc[0]), 0), "end": round(float(dc.iloc[-1]), 0),
        "tot_ret_pct": round(100 * (float(dc.iloc[-1] / dc.iloc[0]) - 1), 1),
        "ann_vol_pct": round(100 * float(dr.std() * np.sqrt(365)), 1),
        "sharpe_rf0": round(float(dr.mean() / dr.std() * np.sqrt(365)), 2),
        "max_dd_4h_pct": round(100 * float(dd), 1),
        "pct_up_days": round(100 * float((dr > 0).mean()), 1),
        "worst_day_pct": round(100 * float(dr.min()), 1),
        "best_day_pct": round(100 * float(dr.max()), 1),
    })
yearly = pd.DataFrame(rows)
yearly.to_csv(f"{OUT}/yearly_stats.csv", index=False)

# ---------- realized vol regimes ----------
rv30 = ret4h.rolling(180).std() * np.sqrt(BPY)  # 30d realized vol, annualized
rv30 = rv30.dropna()
qs = rv30.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
vol_dist = {"rv30_percentiles_pct": {str(k): round(100 * float(v), 1) for k, v in qs.items()},
            "rv30_by_year_median_pct": {str(y): round(100 * float(rv30[rv30.index.year == y].median()), 1)
                                        for y in sorted(set(rv30.index.year))}}
with open(f"{OUT}/vol_distribution.json", "w") as fh:
    json.dump(vol_dist, fh, indent=2)

# vol terciles (full-sample, characterization only)
t1, t2 = rv30.quantile([1/3, 2/3])
vol_reg = pd.Series(np.where(rv30 <= t1, "low_vol", np.where(rv30 <= t2, "mid_vol", "high_vol")),
                    index=rv30.index)

# trend state: close vs 200d SMA (daily, mapped to 4h)
sma200 = dclose.rolling(200).mean()
sma200_4h = sma200.reindex(px.index, method="ffill")
trend = pd.Series(np.where(px > sma200_4h, "above200d", "below200d"), index=px.index)

fwd30 = px.shift(-180) / px - 1  # forward 30d return
fwd7 = px.shift(-42) / px - 1

def cell_stats(mask, fwd):
    mask = mask.reindex(fwd.index, fill_value=False)
    r = fwd[mask].dropna()
    if len(r) < 30:
        return None
    return {"n": int(len(r)), "mean_pct": round(100 * float(r.mean()), 2),
            "median_pct": round(100 * float(r.median()), 2),
            "std_pct": round(100 * float(r.std()), 2),
            "t_raw": round(float(r.mean() / (r.std() / np.sqrt(len(r)))), 2),
            "pct_pos": round(100 * float((r > 0).mean()), 1)}

grid = []
for vr in ["low_vol", "mid_vol", "high_vol"]:
    for tr in ["above200d", "below200d"]:
        m = (vol_reg == vr) & (trend == tr)
        for hname, fwd in [("fwd_7d", fwd7), ("fwd_30d", fwd30)]:
            s = cell_stats(m, fwd)
            if s:
                s.update({"vol_regime": vr, "trend": tr, "horizon": hname})
                grid.append(s)
# unconditional by vol regime and by trend
for vr in ["low_vol", "mid_vol", "high_vol"]:
    s = cell_stats(vol_reg == vr, fwd30)
    if s:
        s.update({"vol_regime": vr, "trend": "ALL", "horizon": "fwd_30d"}); grid.append(s)
for tr in ["above200d", "below200d"]:
    s = cell_stats(trend == tr, fwd30)
    if s:
        s.update({"vol_regime": "ALL", "trend": tr, "horizon": "fwd_30d"}); grid.append(s)
s = cell_stats(pd.Series(True, index=px.index), fwd30)
s.update({"vol_regime": "ALL", "trend": "ALL", "horizon": "fwd_30d"}); grid.append(s)

pd.DataFrame(grid).to_csv(f"{OUT}/regime_forward_returns.csv", index=False)

# regime persistence: P(same vol tercile 30d later)
same = (vol_reg == vol_reg.shift(-180)).mean()
persist = {"p_same_vol_tercile_after_30d": round(float(same), 3),
           "chance_level": 0.333,
           "trend_state_persistence_30d": round(float((trend == trend.shift(-180)).mean()), 3)}
with open(f"{OUT}/regime_persistence.json", "w") as fh:
    json.dump(persist, fh, indent=2)

print("=== OVERVIEW ==="); print(json.dumps(overview, indent=2))
print("\n=== YEARLY ==="); print(yearly.to_string(index=False))
print("\n=== VOL DIST ==="); print(json.dumps(vol_dist, indent=2))
print("\n=== REGIME GRID (fwd_30d) ===")
print(pd.DataFrame([g for g in grid if g["horizon"] == "fwd_30d"]).to_string(index=False))
print("\n=== PERSISTENCE ==="); print(json.dumps(persist, indent=2))
