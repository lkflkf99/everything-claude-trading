"""bt_03b: DIAGNOSE the A1 FULL stamp-vs-parity gap (-46.9bp/yr CAGR, MDD -42.5 vs -38.9).

Decomposition ladder (A1, FULL window):
  QR-parity (reference, daily-close exec + daily-sum funding + weight accounting)
  V_close  = stamp-exact harness but execution AT the 00:00 print (p=close[t]),
             real funding stamps, db0  -> isolates funding-convention + fixed-q effects
  V_p05    = stamp-exact, exec at 00:05-bar open, real stamps, db0 (= bt_03 db0)
             -> V_p05 - V_close = pure 5-min execution-price effect on flip days
  V_db5    = spec config (deadband 5%)                          -> deadband effect

Also: per-flip-day execution price diff (p05 vs close) for every trade day of A1,
and trough-date comparison of the equity curves.

Outputs: bt_stamp_diagnose.json
"""
import pandas as pd, numpy as np, json, sys
sys.path.insert(0, "research/highrisk")
from bt_common import OUT, TC
from qr_utils import perf_stats

E0 = 10_000.0
STEP = 0.001
MIN_NOTIONAL = 50.0

daily = pd.read_csv(f"{OUT}/bt_daily.csv", index_col=0, parse_dates=True)
idx = daily.index
close = daily["close"].values
w = (daily["gate"].values * daily["m_vb"].values)   # A1 decided weight

m5 = pd.read_csv("research/data/binance_um_btcusdt_perp_5m.csv",
                 usecols=["open_time_utc", "open"], parse_dates=["open_time_utc"])
m5 = m5.set_index("open_time_utc").sort_index()
b0005 = m5[(m5.index.hour == 0) & (m5.index.minute == 5)]["open"]
p05 = {d.normalize(): v for d, v in b0005.items()}

f = pd.read_csv("research/data/binance_um_btcusdt_perp_funding.csv",
                parse_dates=["funding_time_utc"]).set_index("funding_time_utc").sort_index()
f["funding_rate"] = f["funding_rate"].astype(float)
f["mark_price"] = pd.to_numeric(f["mark_price"], errors="coerce")
stamps = {}
for ts, row in f.iterrows():
    stamps.setdefault(ts.normalize(), []).append((ts, row["funding_rate"], row["mark_price"]))


def run(w_target, deadband, price_mode):
    """price_mode: 'p05' = 00:05-bar open at day t+1; 'close' = print close[t]."""
    n = len(idx)
    C, q = E0, 0.0
    S = np.full(n, np.nan)
    fills = []
    for t in range(n):
        day = idx[t] + pd.Timedelta(days=1)
        for ts, rate, mark in stamps.get(day, []):
            if ts.hour == 0 and q != 0.0:
                mk = mark if np.isfinite(mark) else close[t]
                C += -q * mk * rate
        S[t] = C + q * close[t]
        wt = w_target[t]
        p = close[t] if price_mode == "close" else p05.get(day, np.nan)
        if np.isfinite(p):
            E = C + q * p
            qstar = np.floor(wt * E / p / STEP) * STEP if wt * E >= MIN_NOTIONAL else 0.0
            if wt == 1 and q > 0 and abs(q * p / E - 1.0) <= deadband:
                qstar = q
            dq = qstar - q
            if abs(dq) > 1e-12:
                fee = abs(dq * p) * TC
                C -= dq * p + fee
                q += dq
                fills.append({"t": int(t), "day": str(day.date()), "dq": float(dq),
                              "p_fill": float(p), "p_close": float(close[t])})
        for ts, rate, mark in stamps.get(day, []):
            if ts.hour in (8, 16) and q != 0.0:
                mk = mark if np.isfinite(mark) else close[t]
                C += -q * mk * rate
    ret = np.zeros(n); ret[1:] = S[1:] / S[:-1] - 1.0
    return S, ret, fills


def win(ret):
    m = np.zeros(len(idx), bool); m[200:] = True
    m &= (idx >= "2020-01-01") & (idx <= "2026-10-31")
    return perf_stats(ret[m])


S_c, r_c, fills_c = run(w, 0.0, "close")
S_p, r_p, fills_p = run(w, 0.0, "p05")
S_5, r_5, fills_5 = run(w, 0.05, "p05")

st_c, st_p, st_5 = win(r_c), win(r_p), win(r_5)
qr = perf_stats(daily["ret_A1_VB"].values[(np.arange(len(idx)) >= 200) &
                                          (idx >= "2020-01-01") & (idx <= "2026-10-31")])

# equity troughs
def trough(S):
    eq = S / S[0]
    pk = np.maximum.accumulate(eq)
    dd = eq / pk - 1
    t = int(np.nanargmin(dd))
    return {"trough_date": str(idx[t].date()), "mdd": float(dd[t])}

# per-fill price diff (only weight-change fills matter for timing noise; report all)
fd = pd.DataFrame(fills_p)
fd["slip_bp_vs_close"] = np.sign(fd["dq"]) * (fd["p_fill"] / fd["p_close"] - 1) * 1e4
# signed so that >0 = worse fill (paid more on buy, received less on sell)
# aggregate signed impact: buy dq>0 at slip s (>0 worse): cost = dq*p_close*s;
# sell dq<0: receive less by |dq|*p_close*s
fd["slip_usdt"] = fd["slip_bp_vs_close"] / 1e4 * fd["dq"].abs() * fd["p_close"]
big = fd.reindex(fd["slip_bp_vs_close"].abs().sort_values(ascending=False).index).head(15)

out = {
    "ladder_FULL": {
        "qr_parity": {"cagr": qr["cagr"], "mdd": qr["mdd"], "sharpe": qr["sharpe"]},
        "V_close_exec_real_stamps_db0": {"cagr": st_c["cagr"], "mdd": st_c["mdd"], "sharpe": st_c["sharpe"]},
        "V_p05_exec_real_stamps_db0": {"cagr": st_p["cagr"], "mdd": st_p["mdd"], "sharpe": st_p["sharpe"]},
        "V_p05_exec_real_stamps_db5_spec": {"cagr": st_5["cagr"], "mdd": st_5["mdd"], "sharpe": st_5["sharpe"]},
    },
    "deltas_bp_per_yr": {
        "funding_convention_plus_fixed_q (close_exec - qr_parity)": 1e4 * (st_c["cagr"] - qr["cagr"]),
        "5min_exec_price (p05 - close)": 1e4 * (st_p["cagr"] - st_c["cagr"]),
        "deadband (db5 - db0)": 1e4 * (st_5["cagr"] - st_p["cagr"]),
        "total (db5 - qr_parity)": 1e4 * (st_5["cagr"] - qr["cagr"]),
    },
    "troughs": {"qr_parity_equiv": None, "close_exec": trough(S_c), "p05_exec": trough(S_p),
                "p05_db5": trough(S_5)},
    "fill_slip_stats": {"n_fills": int(len(fd)),
                        "sum_slip_usdt": float(fd["slip_usdt"].sum()),
                        "mean_abs_slip_bp": float(fd["slip_bp_vs_close"].abs().mean()),
                        "worst_15_fills": big[["day", "dq", "p_fill", "p_close",
                                               "slip_bp_vs_close", "slip_usdt"]].to_dict("records")},
}
with open(f"{OUT}/bt_stamp_diagnose.json", "w") as fh:
    json.dump(out, fh, indent=2)
print(json.dumps(out, indent=2))
