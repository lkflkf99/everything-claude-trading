# -*- coding: utf-8 -*-
"""
Round-4 carry mechanism analysis: BTCUSDT perp funding harvest (short perp, collect funding).
All numbers computed from local CSVs. No fabricated values.
"""
import pandas as pd
import numpy as np

DATA = "research/data"

# ---------------------------------------------------------------- load
f = pd.read_csv(f"{DATA}/binance_um_btcusdt_perp_funding.csv",
                parse_dates=["funding_time_utc"])
f = f.sort_values("funding_time_ms").reset_index(drop=True)
f["year"] = f["funding_time_utc"].dt.year
r = f["funding_rate"].values
n = len(r)
PERIODS_PER_YEAR = 3 * 365  # 8h funding

print("=" * 78)
print("SECTION 1: CARRY STREAM STATISTICS (short 1 unit notional, always-on)")
print("=" * 78)
print(f"sample: {f['funding_time_utc'].iloc[0]} .. {f['funding_time_utc'].iloc[-1]}  N={n}")
print(f"mean/8h = {r.mean()*1e4:.4f} bp   median = {np.median(r)*1e4:.4f} bp")
print(f"annualized (mean*{PERIODS_PER_YEAR}) = {r.mean()*PERIODS_PER_YEAR*100:.2f}%")
print(f"share positive = {(r>0).mean()*100:.1f}%   share zero = {(r==0).mean()*100:.1f}%   share negative = {(r<0).mean()*100:.1f}%")
print(f"min = {r.min()*1e4:.2f} bp   max = {r.max()*1e4:.2f} bp")
print(f"share at +0.01% (default rate) = {(np.isclose(r,0.0001)).mean()*100:.1f}%")
print(f"share >= 0.03% = {(r>=0.0003).mean()*100:.1f}%   share >= 0.05% = {(r>=0.0005).mean()*100:.1f}%   share >= 0.10% = {(r>=0.001).mean()*100:.1f}%")

# yearly table
print("\n--- annualized carry by calendar year ---")
print(f"{'year':<6}{'N':>6}{'mean_bp/8h':>12}{'ann_%':>9}{'%pos':>8}{'%neg':>8}{'min_bp':>9}{'max_bp':>9}{'ann_ex_top5%':>14}")
for y, g in f.groupby("year"):
    rr = g["funding_rate"].values
    full = len(rr) >= 1000
    # robustness: annualized after clipping top 5% (winsorize) to see concentration
    cap = np.quantile(rr, 0.95)
    ann_clip = np.minimum(rr, cap).mean() * PERIODS_PER_YEAR * 100
    print(f"{y:<6}{len(rr):>6}{rr.mean()*1e4:>12.4f}{rr.mean()*PERIODS_PER_YEAR*100:>9.2f}"
          f"{(rr>0).mean()*100:>8.1f}{(rr<0).mean()*100:>8.1f}{rr.min()*1e4:>9.2f}{rr.max()*1e4:>9.2f}{ann_clip:>14.2f}")

# regime split by price trend (200d MA on 4h close, resampled to funding times)
h = pd.read_csv(f"{DATA}/binance_um_btcusdt_perp_4h.csv", parse_dates=["open_time_utc"])
h = h.sort_values("open_time_ms").reset_index(drop=True)
h["ma200d"] = h["close"].rolling(200 * 6).mean()  # 200 days of 4h bars
px = h.set_index("open_time_utc")["close"]
ma = h.set_index("open_time_utc")["ma200d"]
f["px"] = f["funding_time_utc"].map(px)
f["ma200d"] = f["funding_time_utc"].map(ma)
f["bull"] = f["px"] > f["ma200d"]
print("\n--- carry by trend regime (BTC 4h close vs 200d MA) ---")
for lab, g in f.dropna(subset=["bull"]).groupby("bull"):
    rr = g["funding_rate"].values
    print(f"{'above 200d MA (bull)' if lab else 'below 200d MA (bear)':<26}"
          f"N={len(rr):>5}  mean={rr.mean()*1e4:>7.4f} bp/8h  ann={rr.mean()*PERIODS_PER_YEAR*100:>6.2f}%  "
          f"%pos={(rr>0).mean()*100:>5.1f}  %neg={(rr<0).mean()*100:>5.1f}")

# drawdown / underwater of carry stream
print("\n--- negative-funding stretches ---")
neg = r < 0
runs = []
i = 0
while i < n:
    if neg[i]:
        j = i
        while j < n and neg[j]:
            j += 1
        runs.append((i, j - i, r[i:j].sum(), r[i:j].min()))
        i = j
    else:
        i += 1
runs_df = pd.DataFrame(runs, columns=["start_idx", "len", "cum_rate", "min_rate"])
runs_df["start"] = f["funding_time_utc"].iloc[runs_df["start_idx"]].values
print(f"number of negative runs: {len(runs_df)}")
print(f"duration (periods): median={runs_df['len'].median():.0f}  p90={runs_df['len'].quantile(.9):.0f}  "
      f"p99={runs_df['len'].quantile(.99):.0f}  max={runs_df['len'].max()}")
print(f"cumulative negative carry per run (bp): median={runs_df['cum_rate'].median()*1e4:.1f}  "
      f"p90={runs_df['cum_rate'].quantile(.9)*1e4:.1f}  worst={runs_df['cum_rate'].min()*1e4:.1f}")
print("\ntop-8 worst negative stretches:")
top = runs_df.nsmallest(8, "cum_rate")
for _, row in top.iterrows():
    print(f"  start={row['start']}  len={int(row['len'])} periods ({row['len']/3:.1f} days)  "
          f"cum={row['cum_rate']*1e4:.1f} bp  min_1p={row['min_rate']*1e4:.2f} bp")

# longest run of ANY sign streak around zero incl tiny positives? also longest time below 0 cumulatively
# equity curve of carry (in % of notional), underwater analysis
eq = np.cumsum(r) * 100  # percent of notional
peak = np.maximum.accumulate(eq)
uw = eq - peak
print(f"\ncarry equity curve: total = {eq[-1]:.2f}% of notional over {n/PERIODS_PER_YEAR:.2f} yrs")
print(f"max drawdown of carry stream = {uw.min():.3f}% of notional")
# longest underwater period
uw_bool = uw < -1e-12
runs_uw = []
i = 0
while i < n:
    if uw_bool[i]:
        j = i
        while j < n and uw_bool[j]:
            j += 1
        runs_uw.append(j - i)
        i = j
    else:
        i += 1
print(f"longest underwater stretch = {max(runs_uw)} periods = {max(runs_uw)/3:.1f} days")

# Sharpe of carry stream
mu, sd = r.mean(), r.std(ddof=1)
sharpe = mu / sd * np.sqrt(PERIODS_PER_YEAR)
print(f"\ncarry stream Sharpe (8h mean/std * sqrt(1095)) = {sharpe:.2f}")
print(f"  std/8h = {sd*1e4:.4f} bp")
# yearly Sharpe
for y, g in f.groupby("year"):
    rr = g["funding_rate"].values
    if rr.std() > 0:
        print(f"  {y}: Sharpe = {rr.mean()/rr.std()*np.sqrt(PERIODS_PER_YEAR):>6.2f}")

# autocorrelation
print("\n--- funding rate autocorrelation ---")
x = r - r.mean()
denom = (x ** 2).sum()
for lag in [1, 2, 3, 6, 9, 15, 30, 60, 90, 180]:
    ac = (x[:-lag] * x[lag:]).sum() / denom
    print(f"  lag {lag:>3} ({lag/3:>5.1f} d): {ac:>6.3f}")
# AR(1) half-life
phi1 = (x[:-1] * x[1:]).sum() / (x[:-1] ** 2).sum()
hl = np.log(0.5) / np.log(abs(phi1))
print(f"  AR(1) phi = {phi1:.3f}  -> half-life = {hl:.1f} periods = {hl/3:.1f} days")
# Ljung-Box (manual, k=30)
k = 30
acf = np.array([(x[:-l] * x[l:]).sum() / denom for l in range(1, k + 1)])
lb = n * (n + 2) * np.sum(acf ** 2 / (n - np.arange(1, k + 1)))
print(f"  Ljung-Box Q(30) = {lb:.1f} (chi2 crit 5% ~ 43.8)")

# conditional persistence: decile of current funding -> mean next-period & next-5-period funding
print("\n--- conditioning table: current funding decile -> future carry ---")
df = pd.DataFrame({"r": r})
df["r_next1"] = df["r"].shift(-1)
df["r_next5"] = df["r"].rolling(5).sum().shift(-5)
df["dec"] = pd.qcut(df["r"], 10, labels=False, duplicates="drop")
print(f"{'decile':<8}{'cur_mean_bp':>12}{'next1_bp':>10}{'next5_bp':>10}")
for d, g in df.groupby("dec"):
    print(f"{d:<8}{g['r'].mean()*1e4:>12.3f}{g['r_next1'].mean()*1e4:>10.3f}{g['r_next5'].mean()*1e4:>10.3f}")

# conditional on sign streaks: after k consecutive negatives, what is next-period carry?
print("\n--- after k consecutive negative fundings ---")
streak = np.zeros(n, dtype=int)
c = 0
for i in range(n):
    c = c + 1 if r[i] < 0 else 0
    streak[i] = c
for k0 in [1, 2, 3, 5, 8]:
    idx = np.where(streak == k0)[0]
    idx = idx[idx + 1 < n]
    if len(idx):
        print(f"  k={k0}: N={len(idx):>4}  next-period mean = {r[idx+1].mean()*1e4:>7.3f} bp  "
              f"P(next<0) = {(r[idx+1]<0).mean()*100:.1f}%")
# after high funding: does it persist?
hi = r >= 0.0005
idx = np.where(hi)[0]; idx = idx[idx + 5 < n]
print(f"\n  after funding >= 5bp: N={len(idx)}  next1 mean = {r[idx+1].mean()*1e4:.3f} bp  "
      f"next5 mean = {np.mean([r[i+1:i+6].mean() for i in idx])*1e4:.3f} bp")

print()
print("=" * 78)
print("SECTION 2: PRE/POST 2025-09-18 FUNDING FORMULA CHANGE (data check)")
print("=" * 78)
cut = pd.Timestamp("2025-09-18")
pre = f[f["funding_time_utc"] < cut]["funding_rate"]
post = f[f["funding_time_utc"] >= cut]["funding_rate"]
for lab, g in [("pre  2019-09..2025-09", pre), ("post 2025-09-18..now", post)]:
    print(f"{lab}: N={len(g)}  mean={g.mean()*1e4:.4f} bp  ann={g.mean()*PERIODS_PER_YEAR*100:.2f}%  "
          f"%pos={(g>0).mean()*100:.1f}  %at_default={(np.isclose(g,0.0001)).mean()*100:.1f}  "
          f"min={g.min()*1e4:.2f} bp  max={g.max()*1e4:.2f} bp")
# 90d rolling mean around the cut
f["roll90"] = f["funding_rate"].rolling(270).mean() * PERIODS_PER_YEAR * 100
near = f[(f["funding_time_utc"] > cut - pd.Timedelta(days=120)) &
         (f["funding_time_utc"] < cut + pd.Timedelta(days=120))]
print("rolling-90d annualized carry around cut (every 30d):")
print(near.iloc[::90][["funding_time_utc", "roll90"]].to_string(index=False))

print()
print("=" * 78)
print("SECTION 3: SHORT-LEG LIQUIDATION MATH + HISTORICAL TRIGGER SCAN")
print("=" * 78)
# Binance linear perp, isolated short. Approx liq distance (price UP) for leverage L:
# d ~ (1/L - MMR) / (1 + MMR); use MMR=0.5% (BTCUSDT small tiers, <=50k notional: MMR 0.4%; use 0.5% conservative)
MMR = 0.005
print("liquidation distance for isolated short (price rise from entry), MMR=0.5%:")
for L in [1, 2, 3, 5, 10]:
    d = (1 / L - MMR) / (1 + MMR)
    print(f"  {L}x: {d*100:.1f}% adverse move wipes margin")

# historical max adverse excursions: from every funding anchor, max price rise over forward windows
print("\n--- max forward price rise (close-to-close, perp 4h) over horizons ---")
close = h["close"].values
highs = h["high"].values
for H, lab in [(30 * 6, "30d"), (90 * 6, "90d"), (180 * 6, "180d"), (365 * 6, "365d")]:
    # rolling forward max of HIGH relative to current close
    fwd_max = pd.Series(highs).iloc[::-1].rolling(H).max().iloc[::-1].values
    adv = fwd_max / close - 1
    print(f"  {lab}: median={np.nanmedian(adv)*100:>6.1f}%  p90={np.nanquantile(adv,.9)*100:>6.1f}%  "
          f"p99={np.nanquantile(adv,.99)*100:>6.1f}%  max={np.nanmax(adv)*100:>7.1f}%")

# episodes: largest N-day rallies in history
print("\n--- largest historical rallies (close basis) ---")
for H, lab in [(30 * 6, "30d"), (90 * 6, "90d"), (180 * 6, "180d")]:
    ret = pd.Series(close).pct_change(H)
    t5 = ret.nlargest(5)
    print(f"  top-5 {lab} rallies:")
    for ts_i, v in t5.items():
        print(f"    ending {h['open_time_utc'].iloc[ts_i]} : +{v*100:.0f}%")

# rebalance simulation: re-anchor when price rises TH% since last anchor (short leg loss = TH% of notional)
# at each rebalance, top up margin from spot side (transfer) OR reduce both legs (trade cost).
print("\n--- rebalance event counts (anchor reset when price +TH% since anchor) ---")
for TH in [0.10, 0.15, 0.20, 0.30]:
    events = []
    anchor = close[0]
    for i in range(1, len(close)):
        if highs[i] / anchor - 1 >= TH:
            events.append(h["open_time_utc"].iloc[i])
            anchor = close[i]
    ev = pd.to_datetime(events)
    per_year = pd.Series(1, index=ev).resample("YE").count() if len(ev) else pd.Series(dtype=int)
    print(f"  TH={TH*100:.0f}%: total={len(events)} over {(h['open_time_utc'].iloc[-1]-h['open_time_utc'].iloc[0]).days/365.25:.1f} yrs"
          f"  (avg {len(events)/((h['open_time_utc'].iloc[-1]-h['open_time_utc'].iloc[0]).days/365.25):.1f}/yr)")
    if len(ev):
        print(f"    by year: {dict(per_year)}")

# effective leverage implied by top-up rule: keep margin = q of notional; liquidation when rise > (q - MMR)
print("\n--- margin-buffer design table (isolated short) ---")
print("margin posted q (% of notional) -> liquidation distance & effective leverage")
for q in [0.10, 0.20, 0.33, 0.50, 1.00]:
    d = (q - MMR) / (1 + MMR)
    print(f"  q={q*100:>5.0f}%  (eff. lev {1/q:>4.1f}x): liq at +{d*100:>6.1f}% adverse; "
          f"capital = q*notional on perp leg")

# gap risk: largest single-bar and single-day up moves (adverse for short)
bar_ret = pd.Series(close).pct_change()
day_ret = pd.Series(close).pct_change(6)
print(f"\nlargest 4h up bar: {bar_ret.max()*100:.1f}%   largest 24h up move: {day_ret.max()*100:.1f}%")
print(f"p99.9 4h up bar: {bar_ret.quantile(.999)*100:.2f}%   p99.9 24h up: {day_ret.quantile(.999)*100:.2f}%")

print()
print("=" * 78)
print("SECTION 4: MARK vs PERP (spot-leg proxy assessment)")
print("=" * 78)
m = pd.read_csv(f"{DATA}/binance_um_btcusdt_perp_mark_5m.csv", parse_dates=["open_time_utc"])
p = pd.read_csv(f"{DATA}/binance_um_btcusdt_perp_5m.csv", parse_dates=["open_time_utc"],
                usecols=["open_time_ms", "open_time_utc", "close"])
mm = m.merge(p.rename(columns={"close": "close_perp", "open_time_utc": "utc_perp"}), on="open_time_ms")
mm = mm.rename(columns={"close": "close_mark", "open_time_utc": "utc"})
mm["spread_bp"] = (mm["close_perp"] / mm["close_mark"] - 1) * 1e4
mm["date"] = mm["utc"].dt.date
s = mm["spread_bp"]
print(f"merged 5m bars: {len(mm)}")
print(f"perp-mark spread (bp): mean={s.mean():.2f}  median={s.median():.2f}  std={s.std():.2f}")
print(f"quantiles (bp): p1={s.quantile(.01):.1f}  p5={s.quantile(.05):.1f}  p95={s.quantile(.95):.1f}  p99={s.quantile(.99):.1f}")
print(f"abs spread: median={s.abs().median():.2f} bp  p95={s.abs().quantile(.95):.2f} bp  max={s.abs().max():.1f} bp")
# annualized value of spread drift if used as spot proxy: daily mean spread change
dly = mm.groupby("date")["spread_bp"].last()
print(f"daily spread level: mean={dly.mean():.2f} bp  std of daily change={dly.diff().std():.2f} bp")
print(f"annualized spread-drift risk (std*sqrt(365)) = {dly.diff().std()*np.sqrt(365):.1f} bp/yr")
# spread at funding timestamps
mm_f = mm.set_index("utc").reindex(f["funding_time_utc"])
sf = mm_f["spread_bp"].dropna()
print(f"spread at funding times: mean={sf.mean():.2f} bp  std={sf.std():.2f} bp  |p95|={sf.abs().quantile(.95):.1f} bp")
# correlation of spread with funding
tmp = pd.DataFrame({"spread": sf.values, "funding": f.set_index('funding_time_utc')['funding_rate'].reindex(sf.index).values}).dropna()
print(f"corr(spread_at_funding, funding_rate) = {tmp['spread'].corr(tmp['funding']):.3f}")
# 8h mark return vs perp return divergence (hedge slippage over funding period)
mm8 = mm.set_index("utc").resample("8h").last().dropna(subset=["close_mark", "close_perp"])
rm = mm8["close_mark"].pct_change().dropna()
rp = mm8["close_perp"].pct_change().dropna()
diff = (rp - rm).dropna() * 1e4
print(f"8h return diff (perp - mark), bp: mean={diff.mean():.3f}  std={diff.std():.2f}  "
      f"p1={diff.quantile(.01):.1f}  p99={diff.quantile(.99):.1f}")
print(f"annualized hedge-noise (std*sqrt(1095)) = {diff.std()*np.sqrt(1095):.1f} bp/yr ~ {diff.std()*np.sqrt(1095)/100:.2f}%/yr")
