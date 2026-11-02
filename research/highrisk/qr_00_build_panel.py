"""qr_00: Build master daily panel for quant-research validation.

Daily (UTC) panel from local data only:
  - perp close, daily return (from 4h bars)
  - funding: daily sum/mean/last of the 00/08/16 UTC events (decimal rate)
  - taker imbalance: sum(taker_buy_volume)/sum(volume) from 5m bars
  - rv30: rolling 30d std of daily returns, annualized
  - sma200 / above200d trend state (daily close basis)
  - fund_z: funding z-score vs trailing 365d expanding window (for tilt; lagged use only)

All signals are stamped at day t and are tradable at close of day t (00:00 UTC t+1).
"""
import pandas as pd, numpy as np, os

OUT = "research/highrisk"
os.makedirs(OUT, exist_ok=True)

# ---------- price (4h -> daily) ----------
pxdf = pd.read_csv("research/data/binance_um_btcusdt_perp_4h.csv", parse_dates=["open_time_utc"])
px = pxdf.set_index("open_time_utc")["close"].astype(float).sort_index()
dclose = px.resample("1D").last().dropna()
dclose.name = "close"

# ---------- funding ----------
f = pd.read_csv("research/data/binance_um_btcusdt_perp_funding.csv", parse_dates=["funding_time_utc"])
f = f.set_index("funding_time_utc").sort_index()
f["funding_rate"] = f["funding_rate"].astype(float)
f = f[f.index >= dclose.index[0]]
fd = f["funding_rate"].resample("1D")
fund_sum = fd.sum().rename("fund_sum")      # total funding paid that day (long pays +)
fund_mean = fd.mean().rename("fund_mean")   # avg 8h rate that day
fund_last = fd.last().rename("fund_last")   # last 8h rate (16:00 UTC event)
fund_n = fd.count().rename("fund_n")

# ---------- taker imbalance (5m -> daily) ----------
cols = ["open_time_utc", "volume", "taker_buy_volume"]
m = pd.read_csv("research/data/binance_um_btcusdt_perp_5m.csv", usecols=cols, parse_dates=["open_time_utc"])
m["date"] = m["open_time_utc"].dt.floor("D")
g = m.groupby("date")[["taker_buy_volume", "volume"]].sum()
imb = (g["taker_buy_volume"] / g["volume"]).rename("taker_imb")

# ---------- assemble ----------
pan = pd.concat([dclose, fund_sum, fund_mean, fund_last, fund_n, imb], axis=1).dropna(subset=["close"])
pan["ret1"] = pan["close"].pct_change()
pan["rv30"] = pan["ret1"].rolling(30).std() * np.sqrt(365)
pan["sma200"] = pan["close"].rolling(200).mean()
pan["above200d"] = (pan["close"] > pan["sma200"]).astype(float)

# funding signal: 3d rolling mean of daily mean rate (breaks 1bp quantization ties;
# funding autocorr ~0.8/day so smoothing loses nothing). Frozen a priori.
pan["fund_sig"] = pan["fund_mean"].rolling(3, min_periods=1).mean()
# funding z-score: trailing 365d, min 90 obs, using info up to & incl. that day
fs = pan["fund_sig"]
mu = fs.rolling(365, min_periods=90).mean()
sd = fs.rolling(365, min_periods=90).std()
pan["fund_z"] = ((fs - mu) / sd).clip(-3, 3)

# forward returns (simple, close-to-close), for event studies
for h in [1, 7, 30]:
    pan[f"fwd{h}d"] = pan["close"].shift(-h) / pan["close"] - 1.0
    # forward funding carry over same horizon (what a 1x long pays)
    pan[f"fwd{h}d_fund"] = pan["fund_sum"].shift(-h).rolling(h).sum().shift(0) * np.nan  # placeholder
# correct forward funding: sum of fund_sum over next h days (t+1..t+h? or t..t+h-1)
# define fwd return t->t+h using closes at t and t+h; funding paid on position held during (t, t+h]
for h in [1, 7, 30]:
    s = pan["fund_sum"].copy()
    pan[f"fwd{h}d_fund"] = sum(s.shift(-k) for k in range(1, h + 1))

pan = pan.drop(columns=["fund_n"])
pan.to_csv(f"{OUT}/qr_daily_panel.csv", float_format="%.8f")
print(pan.describe().T.to_string())
print("\nrows:", len(pan), "span:", pan.index[0], "->", pan.index[-1])
print("\nmissing per col:\n", pan.isna().sum().to_string())
print("\ntaker_imb describe:\n", pan["taker_imb"].describe().to_string())
print("\nfund_z describe:\n", pan["fund_z"].describe().to_string())
