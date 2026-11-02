"""algo_dd_diag: diagnostics for drawdown-deleverage overlay design (TG1x-hyst2).

NOT a backtest. Computes:
  A. Strategy-equity drawdown episode table (depth, duration, vol context)
  B. rv10 distribution + vol-circuit-breaker trigger traces (state machine only)
  C. DD-ladder trigger trace on strategy equity (state machine only)
  D. Funding stamp economics (post-stamp entry saving, signed)
  E. 00:05 UTC bar liquidity vs 10k USDT order (market impact argument)

Inputs:  qr_final_daily.csv (QR frozen sim), qr_whipsaw.csv,
         ../data/binance_um_btcusdt_perp_funding.csv,
         ../data/binance_um_btcusdt_perp_5m.csv
Outputs: algo_dd_diag.json, algo_dd_episodes.csv, algo_volbreaker_episodes.csv
"""
import pandas as pd, numpy as np, json, sys

OUT = "research/highrisk"
TC = 0.0005

# ---------- load ----------
d = pd.read_csv(f"{OUT}/qr_final_daily.csv", index_col=0, parse_dates=True)
d.index = pd.to_datetime(d.index)
w_held = d["w_TG1x_hyst2"].values          # weight HELD during day t
ret_strat = d["ret_TG1x_hyst2"].values     # net daily strat return
ret_btc = d["ret_btc"].values
gate = d["gate_hyst"].values               # state(t) from close(t)
close = d["close"].values
idx = d.index

equity = np.cumprod(1.0 + ret_strat)
peak = np.maximum.accumulate(equity)
dd = equity / peak - 1.0

# rv10 (simple daily returns, annualized) — decision at close(t) uses ret[t-9..t]
rv10 = pd.Series(ret_btc, index=idx).rolling(10).std(ddof=1).values * np.sqrt(365)
rv30 = d["rv30"].values

# ---------- A. strategy drawdown episodes ----------
episodes = []
in_ep = False
for t in range(len(idx)):
    if not in_ep and dd[t] <= -0.10:
        in_ep = True; start = t; trough = t
    elif in_ep:
        if dd[t] < dd[trough]:
            trough = t
        if dd[t] > -0.005 or t == len(idx) - 1:   # recovered (within 0.5%) or end
            seg = slice(start, t + 1)
            episodes.append({
                "peak_date": str(idx[start - 1].date()) if start > 0 else str(idx[0].date()),
                "trough_date": str(idx[trough].date()),
                "depth_pct": round(100 * dd[trough], 1),
                "days_to_trough": int(trough - start + 1),
                "days_underwater": int(t - start + 1),
                "recovered": bool(dd[t] > -0.005),
                "rv10_at_peak": round(float(rv10[start - 1]) * 100, 0) if np.isfinite(rv10[start - 1]) else None,
                "rv10_max_in_ep": round(float(np.nanmax(rv10[seg])) * 100, 0),
                "rv10_crossed_100_before_trough": bool(np.nanmax(rv10[start:trough + 1]) > 1.0),
                "gate_off_days_in_ep": int((gate[seg] == 0).sum()),
            })
            in_ep = False
ep_df = pd.DataFrame(episodes)
ep_df.to_csv(f"{OUT}/algo_dd_episodes.csv", index=False)

# equity peak of the 2021 episode for reference
eq_peak_date = str(idx[np.argmax(equity[:list(idx).index(pd.Timestamp("2021-06-01"))])].date())

# ---------- B. vol circuit breaker state machine (X=100%, k=5) ----------
def volbreaker_trace(X, k):
    """overlay state machine. Returns (m applied on day t, episodes list).
    Decision at close(t-1) applies to day t: m[t] = f(rv10[t-1], state)."""
    m = np.ones(len(idx))
    state = 1           # 1 = ON (trading allowed), 0 = OFF (de-risked)
    below = 0           # consecutive days with rv10 <= X
    eps = []; cur = None
    for t in range(len(idx)):
        m[t] = state
        r = rv10[t]
        if not np.isfinite(r):
            continue
        if state == 1 and r > X:
            state = 0; below = 0
            cur = {"trigger_date": str(idx[t].date()), "rv10_at_trigger": round(float(r) * 100, 0)}
        elif state == 0:
            if r <= X:
                below += 1
                if below >= k:
                    state = 1; below = 0
                    cur["rearm_date"] = str(idx[t].date())
                    cur["days_off"] = int((idx[t] - pd.Timestamp(cur["trigger_date"])).days)
                    eps.append(cur); cur = None
            else:
                below = 0
    if cur is not None:
        cur["rearm_date"] = "open"; cur["days_off"] = int((idx[-1] - pd.Timestamp(cur["trigger_date"])).days)
        eps.append(cur)
    return m, eps

m100, vb_eps = volbreaker_trace(1.00, 5)
vb_df = pd.DataFrame(vb_eps)
vb_df.to_csv(f"{OUT}/algo_volbreaker_episodes.csv", index=False)

# sensitivity context (episode counts / days off only — NOT for re-picking)
sens = {}
for X in [0.80, 0.90, 1.00, 1.10, 1.20]:
    mx, ex = volbreaker_trace(X, 5)
    # extra round trips vs gate-only: count m-transitions while gate==1
    dm = np.abs(np.diff(mx))
    extra_rt = float(dm[gate[1:] == 1].sum() / 2.0)
    yrs = len(idx) / 365.25
    sens[f"X{int(X*100)}"] = {
        "n_episodes": len(ex),
        "days_off": int((mx == 0).sum()),
        "extra_round_trips_per_yr": round(extra_rt / yrs, 1),
        "extra_cost_bp_per_yr": round(extra_rt / yrs * 2 * TC * 1e4, 0),
    }

# whipsaw-cluster coverage: was breaker OFF during each losing 2021 mini-episode?
whip = pd.read_csv(f"{OUT}/qr_whipsaw.csv")
whip["entry"] = pd.to_datetime(whip["entry"]); whip["exit"] = pd.to_datetime(whip["exit"])
m100s = pd.Series(m100, index=idx)
def frac_off(a, b):
    seg = m100s[a:b]
    return round(float((seg == 0).mean()), 2) if len(seg) else None
whip["frac_days_breaker_off"] = [frac_off(a, b) for a, b in zip(whip["entry"], whip["exit"])]

# rv10 distribution
held = w_held > 0.5
rv_pct = {}
for lbl, mask in [("all_days", np.isfinite(rv10)),
                  ("held_days", np.isfinite(rv10) & held),
                  ("gate_on_days", np.isfinite(rv10) & (gate == 1))]:
    r = rv10[mask] * 100
    rv_pct[lbl] = {f"p{p}": round(float(np.percentile(r, p)), 0) for p in [50, 75, 90, 95, 99]}
    rv_pct[lbl]["frac_gt_100"] = round(float((r > 100).mean()), 3)

# key dates 2021
key = {}
for ds in ["2021-04-14", "2021-04-18", "2021-05-04", "2021-05-12", "2021-05-19",
           "2021-05-20", "2021-08-09", "2021-09-07", "2021-10-01", "2021-12-04"]:
    ts = pd.Timestamp(ds)
    if ts in idx:
        t = list(idx).index(ts)
        key[ds] = {"close": round(float(close[t]), 0),
                   "rv10_pct": round(float(rv10[t]) * 100, 0) if np.isfinite(rv10[t]) else None,
                   "gate": int(gate[t]), "breaker_m_next_day": int(m100[t]),
                   "strat_dd_pct": round(100 * dd[t], 1)}

# ---------- C. DD ladder trace (-30% breach, rearm on next gate 0->1) ----------
lad = {"level": -0.30, "breaches": []}
state = 1
for t in range(1, len(idx)):
    if state == 1 and dd[t] <= -0.30:
        state = 0
        lad["breaches"].append({"breach_date": str(idx[t].date()), "dd_pct": round(100 * dd[t], 1)})
    elif state == 0 and gate[t] == 1 and gate[t - 1] == 0:
        state = 1
        lad["breaches"][-1]["rearm_date"] = str(idx[t].date())
if lad["breaches"] and "rearm_date" not in lad["breaches"][-1]:
    lad["breaches"][-1]["rearm_date"] = "open"
# how deep do episodes go without breaching -30 (ladder blind spot)?
ep_df2 = ep_df.copy()

# ---------- D. funding stamp economics ----------
fund = pd.read_csv("research/data/binance_um_btcusdt_perp_funding.csv", parse_dates=["funding_time_utc"])
fund["date"] = fund["funding_time_utc"].dt.normalize()
fund["hour"] = fund["funding_time_utc"].dt.hour
held_by_date = pd.Series(w_held, index=idx)
fund["held"] = fund["date"].map(held_by_date).fillna(0.0)
fh = fund[fund["held"] > 0.5]
funding_stats = {
    "n_stamps_held": int(len(fh)),
    "mean_stamp_rate_bp": round(float(fh["funding_rate"].mean()) * 1e4, 3),
    "mean_daily_sum_held_bp": round(float(fh.groupby("date")["funding_rate"].sum().mean()) * 1e4, 3),
    "ann_inmarket_drag_pct": round(float(fh.groupby("date")["funding_rate"].sum().mean()) * 365 * 100, 2),
    "frac_stamps_positive": round(float((fh["funding_rate"] > 0).mean()), 3),
}
# round trips per year (gate entries)
entries = whip["entry"]
yrs = len(idx) / 365.25
funding_stats["gate_round_trips_per_yr"] = round(len(whip) / yrs, 1)
# signed saving from entering AFTER the 00:00 stamp on entry day
# (skip that stamp: save rate if positive, lose receipt if negative)
e00 = fund[(fund["hour"] == 0)].set_index("date")["funding_rate"]
sav = [float(e00.get(a.normalize(), 0.0)) for a in entries]
funding_stats["entry_stamp_signed_saving_total_bp"] = round(sum(sav) * 1e4, 1)
funding_stats["entry_stamp_signed_saving_per_yr_bp"] = round(sum(sav) / yrs * 1e4, 1)
funding_stats["entry_stamp_positive_share"] = round(float(np.mean([s > 0 for s in sav])), 2)

# ---------- E. 00:05 bar liquidity vs 10k order ----------
q = pd.read_csv("research/data/binance_um_btcusdt_perp_5m.csv",
                usecols=["open_time_utc", "quote_volume"], parse_dates=["open_time_utc"])
q["hour"] = q["open_time_utc"].dt.hour
q["minute"] = q["open_time_utc"].dt.minute
bar0005 = q[(q["hour"] == 0) & (q["minute"] == 5)]["quote_volume"]
liq = {
    "median_0005_bar_usdt": round(float(bar0005.median()), 0),
    "p5_0005_bar_usdt": round(float(bar0005.quantile(0.05)), 0),
    "min_0005_bar_usdt": round(float(bar0005.min()), 0),
    "median_all_bars_usdt": round(float(q["quote_volume"].median()), 0),
    "order_usdt": 10000.0,
}
liq["order_pct_of_p5_0005_bar"] = round(100 * 10000.0 / liq["p5_0005_bar_usdt"], 4)

# ---------- summary ----------
summ = {
    "equity_peak_2021_date": eq_peak_date,
    "mdd_full_pct": round(100 * dd.min(), 1),
    "mdd_oos_pct": round(100 * (equity[list(idx).index(pd.Timestamp("2022-01-01")):] /
                                np.maximum.accumulate(equity[list(idx).index(pd.Timestamp("2022-01-01")):]) - 1).min(), 1),
    "n_dd_episodes_ge10pct": len(ep_df),
    "rv10_percentiles": rv_pct,
    "key_dates_2021": key,
    "volbreaker_X100_k5": {"n_episodes": len(vb_eps),
                           "days_off_total": int((m100 == 0).sum()),
                           "episodes_head": vb_eps[:12]},
    "volbreaker_sensitivity": sens,
    "dd_ladder_m30": lad,
    "whipsaw_breaker_coverage": whip[["entry", "exit", "ret_during", "frac_days_breaker_off"]]
        .assign(entry=whip["entry"].dt.date.astype(str), exit=whip["exit"].dt.date.astype(str))
        .to_dict("records"),
    "funding": funding_stats,
    "liquidity": liq,
}
with open(f"{OUT}/algo_dd_diag.json", "w") as f:
    json.dump(summ, f, indent=2, default=str)
print(json.dumps(summ, indent=2, default=str))
