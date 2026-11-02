"""bt_03: STAMP-EXACT rerun — 00:05 UTC execution + real funding stamps.

Event-driven cash/quantity accounting (no weight abstractions):
  cash C, quantity q. Start: C = 10,000 USDT, q = 0.
  For each panel date t (kline day; close[t] prints at 00:00 on day t+1):
    1. 00:00 stamp on day t+1 charged on current q: C -= q * mark * rate
    2. equity sample S[t] = C + q * close[t]          (daily-return series)
    3. decide w = gate[t]*m_overlay[t] (data <= close[t]); execute 00:05 day t+1:
       p = open of the 00:05 5m bar; E = C + q*p
       q* = floor(w*E/p/0.001)*0.001 (0 if w*E < 50 USDT)
       drift deadband: if w==1 and |q*p/E - 1| <= DB -> keep q
       C -= dq*p + |dq*p|*TC ; q += dq
    4. 08:00 / 16:00 stamps on day t+1 charged on post-trade q.

Arms: A1_VB (shipped per selection rule) and A0_baseline (reference).
Each arm x deadband in {0.05 (spec), 0.0 (daily exact)} for the deadband check.

Compare vs QR-parity (bt_daily.csv) on FULL/OOS: |dCAGR| > 10bp/yr => boundary bug.

Outputs: bt_stamp_exact.json, bt_stamp_daily.csv, bt_trade_log.csv
"""
import pandas as pd, numpy as np, json, sys
sys.path.insert(0, "research/highrisk")
from bt_common import OUT, TC, build_panel
from qr_utils import perf_stats

E0 = 10_000.0
STEP = 0.001
MIN_NOTIONAL = 50.0

daily = pd.read_csv(f"{OUT}/bt_daily.csv", index_col=0, parse_dates=True)
idx = daily.index
close = daily["close"].values

# ---------- execution prices: open of the 00:05 bar of each calendar day ----------
m5 = pd.read_csv("research/data/binance_um_btcusdt_perp_5m.csv",
                 usecols=["open_time_utc", "open"], parse_dates=["open_time_utc"])
m5 = m5.set_index("open_time_utc").sort_index()
b0005 = m5[(m5.index.hour == 0) & (m5.index.minute == 5)]["open"]
p05 = {d.normalize(): v for d, v in b0005.items()}

# ---------- funding stamps ----------
f = pd.read_csv("research/data/binance_um_btcusdt_perp_funding.csv",
                parse_dates=["funding_time_utc"]).set_index("funding_time_utc").sort_index()
f["funding_rate"] = f["funding_rate"].astype(float)
f["mark_price"] = pd.to_numeric(f["mark_price"], errors="coerce")
stamps = {}   # Timestamp(day) -> list of (Timestamp, rate, mark)
for ts, row in f.iterrows():
    stamps.setdefault(ts.normalize(), []).append((ts, row["funding_rate"], row["mark_price"]))


def run_stamp(w_target, deadband, label):
    n = len(idx)
    C, q = E0, 0.0
    S = np.full(n, np.nan)
    trades = []
    fund_flows = []           # (exec_day, usdt flow signed: negative = paid)
    missing_p05 = 0
    for t in range(n):
        day = idx[t] + pd.Timedelta(days=1)          # execution calendar day
        # 1. 00:00 stamp (pre-trade quantity)
        for ts, rate, mark in stamps.get(day, []):
            if ts.hour == 0 and q != 0.0:
                mk = mark if np.isfinite(mark) else close[t]
                flow = -q * mk * rate
                C += flow
                fund_flows.append((day, flow))
        # 2. equity sample at the print
        S[t] = C + q * close[t]
        # 3. 00:05 execution
        w = w_target[t]
        p = p05.get(day, np.nan)
        if not np.isfinite(p):
            missing_p05 += 1 if w != (1 if q > 0 else 0) else 0
        else:
            E = C + q * p
            qstar = np.floor(w * E / p / STEP) * STEP if w * E >= MIN_NOTIONAL else 0.0
            if w == 1 and q > 0 and abs(q * p / E - 1.0) <= deadband:
                qstar = q
            dq = qstar - q
            if abs(dq) > 1e-12:
                notional = dq * p
                fee = abs(notional) * TC
                C -= notional + fee
                q += dq
                trades.append({"exec_day": str(day.date()), "dq": dq, "price": p,
                               "fee_usdt": fee, "w_target": w})
        # 4. 08:00 / 16:00 stamps (post-trade quantity)
        for ts, rate, mark in stamps.get(day, []):
            if ts.hour in (8, 16) and q != 0.0:
                mk = mark if np.isfinite(mark) else close[t]
                flow = -q * mk * rate
                C += flow
                fund_flows.append((day, flow))
    ret = np.zeros(n)
    ret[1:] = S[1:] / S[:-1] - 1.0
    return {"label": label, "S": S, "ret": ret, "trades": trades,
            "fund_flows": fund_flows, "missing_p05": missing_p05,
            "final_equity": float(C + q * close[-1])}


def window_stats(ret, label_a, a, b, skip):
    m = (idx >= a) & (idx <= b)
    if skip:
        mm = np.zeros(len(idx), bool); mm[skip:] = True
        m = m & mm
    return perf_stats(ret[m])


runs = {}
for arm, wcol in [("A1_VB", "A1_VB"), ("A0_baseline", "A0_baseline")]:
    w = (daily["gate"].values * daily["m_vb"].values) if arm == "A1_VB" else daily["gate"].values
    for db, dblbl in [(0.05, "db5"), (0.0, "db0")]:
        runs[f"{arm}_{dblbl}"] = run_stamp(w, db, f"{arm}_{dblbl}")

# ---------- comparisons ----------
out = {"accounting": "stamp-exact: 00:05 UTC exec @ 00:05-bar open, real funding stamps, "
                     "qty floor 0.001 BTC, E0=10000 USDT, TC=5bp",
       "windows": {}, "boundary_check": {}, "deadband_check": {}, "funding_per_year": {},
       "trade_stats": {}}
WINS = [("FULL_2020H2_2026", "2020-01-01", "2026-10-31", 200),
        ("OOS_2022_2026", "2022-01-01", "2026-10-31", 0)]
for key, run in runs.items():
    out["windows"][key] = {}
    for lbl, a, b, skip in WINS:
        ps = window_stats(run["ret"], lbl, a, b, skip)
        out["windows"][key][lbl] = {k: ps[k] for k in ["cagr", "sharpe", "ann_vol", "mdd", "total_x", "n"]}
    out["trade_stats"][key] = {"n_trades": len(run["trades"]),
                               "total_fees_usdt": float(sum(t["fee_usdt"] for t in run["trades"])),
                               "missing_p05_days": run["missing_p05"],
                               "final_equity_usdt": run["final_equity"]}

# boundary check: stamp-exact (db5, spec config) vs QR-parity daily accounting
qr = {"A0_baseline": daily["ret_A0_baseline"].values, "A1_VB": daily["ret_A1_VB"].values}
for arm in ["A0_baseline", "A1_VB"]:
    row = {}
    for lbl, a, b, skip in WINS:
        m = (idx >= a) & (idx <= b)
        if skip:
            mm = np.zeros(len(idx), bool); mm[skip:] = True
            m = m & mm
        se = perf_stats(runs[f"{arm}_db5"]["ret"][m])
        qp = perf_stats(qr[arm][m])
        row[lbl] = {"stamp_cagr": se["cagr"], "qr_parity_cagr": qp["cagr"],
                    "dcagr_bp_per_yr": 1e4 * (se["cagr"] - qp["cagr"]),
                    "stamp_mdd": se["mdd"], "qr_parity_mdd": qp["mdd"],
                    "stamp_sharpe": se["sharpe"], "qr_parity_sharpe": qp["sharpe"]}
    ok = all(abs(row[l]["dcagr_bp_per_yr"]) <= 10.0 for l, _, _, _ in WINS)
    row["verdict"] = "OK" if ok else "BOUNDARY BUG - INVESTIGATE"
    out["boundary_check"][arm] = row

# deadband check: db5 vs db0 within stamp-exact
for arm in ["A0_baseline", "A1_VB"]:
    row = {}
    for lbl, a, b, skip in WINS:
        a5 = out["windows"][f"{arm}_db5"][lbl]
        a0 = out["windows"][f"{arm}_db0"][lbl]
        row[lbl] = {"cagr_db5": a5["cagr"], "cagr_db0": a0["cagr"],
                    "dcagr_bp_per_yr": 1e4 * (a5["cagr"] - a0["cagr"])}
    f5 = out["trade_stats"][f"{arm}_db5"]["total_fees_usdt"]
    f0 = out["trade_stats"][f"{arm}_db0"]["total_fees_usdt"]
    row["fees_usdt_db5"] = f5; row["fees_usdt_db0"] = f0
    row["n_trades_db5"] = out["trade_stats"][f"{arm}_db5"]["n_trades"]
    row["n_trades_db0"] = out["trade_stats"][f"{arm}_db0"]["n_trades"]
    out["deadband_check"][arm] = row

# funding paid per calendar year (db5 runs), as USDT and % of start-of-year equity
for arm in ["A0_baseline", "A1_VB"]:
    run = runs[f"{arm}_db5"]
    ff = pd.DataFrame(run["fund_flows"], columns=["day", "flow"])
    ff["year"] = pd.to_datetime(ff["day"]).dt.year
    S = pd.Series(run["S"], index=idx)
    per_yr = {}
    for y, g in ff.groupby("year"):
        soy = S[str(y)].iloc[0] if len(S[str(y)]) else np.nan
        per_yr[int(y)] = {"funding_usdt_signed": round(float(g["flow"].sum()), 2),
                          "pct_of_soy_equity": round(100 * float(g["flow"].sum()) / float(soy), 2)
                          if np.isfinite(soy) else None}
    out["funding_per_year"][arm] = per_yr

# persist daily series + trade log
sd = pd.DataFrame({"close": close}, index=idx)
for key, run in runs.items():
    sd[f"equity_{key}"] = run["S"]
    sd[f"ret_{key}"] = run["ret"]
sd.to_csv(f"{OUT}/bt_stamp_daily.csv", float_format="%.10f")
tl = pd.DataFrame(runs["A1_VB_db5"]["trades"])
tl.to_csv(f"{OUT}/bt_trade_log.csv", index=False)

with open(f"{OUT}/bt_stamp_exact.json", "w") as fh:
    json.dump(out, fh, indent=2, default=str)
print(json.dumps(out, indent=2, default=str))
