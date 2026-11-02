"""04: Autocorrelation structure — 4h/daily returns, vol clustering, variance ratios, stability."""
import pandas as pd, numpy as np, json, os

OUT = "research/highrisk"

df = pd.read_csv("research/data/binance_um_btcusdt_perp_4h.csv", parse_dates=["open_time_utc"])
px = df.set_index("open_time_utc")["close"].astype(float).sort_index()
ret4h = px.pct_change().dropna()
dclose = px.resample("1D").last().dropna()
dret = dclose.pct_change().dropna()

def acf(s, lags):
    return {int(k): round(float(s.autocorr(k)), 4) for k in lags}

def ljung_box(s, lags):
    n = len(s)
    q = 0.0
    for k in range(1, lags + 1):
        r = s.autocorr(k)
        q += r * r / (n - k)
    return round(float(n * (n + 2) * q), 1)

lags4h = list(range(1, 31))
lagsd = list(range(1, 31))
out = {
    "ret4h_acf_lags1_30": acf(ret4h, lags4h),
    "ret4h_ljungbox_lag10": ljung_box(ret4h, 10),
    "ret4h_ljungbox_lag20": ljung_box(ret4h, 20),
    "dret_acf_lags1_30": acf(dret, lagsd),
    "dret_ljungbox_lag10": ljung_box(dret, 10),
    "dret_ljungbox_lag20": ljung_box(dret, 20),
    "abs_ret4h_acf_lag1_5_10_20": {int(k): round(float(ret4h.abs().autocorr(k)), 4) for k in [1, 5, 10, 20]},
    "abs_dret_acf_lag1_5_10_20": {int(k): round(float(dret.abs().autocorr(k)), 4) for k in [1, 5, 10, 20]},
    "conf_band_95_4h": round(1.96 / np.sqrt(len(ret4h)), 4),
    "conf_band_95_daily": round(1.96 / np.sqrt(len(dret)), 4),
}
# variance ratios on daily log returns: VR(k) = Var(k-day sum)/(k*Var(1d))
lr = np.log(dclose).diff().dropna()
def vr(k):
    s = lr.rolling(k).sum().dropna()
    return round(float(s.var() / (k * lr.var())), 3)
out["variance_ratio_daily"] = {int(k): vr(k) for k in [2, 5, 10, 20, 30, 60]}

# weekly/monthly horizon momentum check: autocorr of weekly returns
wclose = dclose.resample("W").last().dropna()
wret = wclose.pct_change().dropna()
out["weekly_ret_acf_lag1_4"] = {int(k): round(float(wret.autocorr(k)), 4) for k in [1, 2, 3, 4]}
mclose = dclose.resample("ME").last().dropna()
mret = mclose.pct_change().dropna()
out["monthly_ret_acf_lag1_3"] = {int(k): round(float(mret.autocorr(k)), 4) for k in [1, 2, 3]}

# stability: daily lag-1 autocorr by year
out["dret_lag1_by_year"] = {str(y): round(float(dret[dret.index.year == y].autocorr(1)), 3)
                            for y in sorted(set(dret.index.year))}
# 4h lag-1 by year
out["ret4h_lag1_by_year"] = {str(y): round(float(ret4h[ret4h.index.year == y].autocorr(1)), 3)
                             for y in sorted(set(ret4h.index.year))}

with open(f"{OUT}/autocorr.json", "w") as fh:
    json.dump(out, fh, indent=2)
print(json.dumps(out, indent=2))
