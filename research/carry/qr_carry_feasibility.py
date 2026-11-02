# -*- coding: utf-8 -*-
"""
Round-4 carry feasibility tests (quant-researcher).
Always-on delta-neutral funding carry on BTCUSDT perp (long spot + short perp).
All numbers computed from local CSVs. No fabricated values.
Convention: carry_i = funding_rate_i  (short perp receives when rate > 0).

Cost model (adopted from crypto-defi-analyst, agreed by risk-manager):
  - deployment round trip (entry+exit, 4 taker legs total): 0.15% of notional, one-off
  - short-leg margin rebalance: 0.30%/yr of notional, charged only while IN position
  - H3/H2 conditional rules: each exit->re-entry cycle = one full round trip = 0.15%
"""
import math
import numpy as np
import pandas as pd

DATA = "research/data"
PPY = 3 * 365          # 8h funding periods per year
RT_COST = 0.0015       # 0.15% round trip (in+out, both legs)
REB_ANN = 0.0030       # 0.30%/yr rebalance drag while in position
REB_PER = REB_ANN / PPY
CUT = pd.Timestamp("2025-09-18")   # funding formula change
NW_LAG = 30            # Newey-West lag in periods (10 days); sensitivity 60/90

# ------------------------------------------------------------- stats helpers
def norm_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))

def norm_ppf(p):
    # Acklam's rational approximation
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1-p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q*q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)

def nw_mean(x, L=NW_LAG):
    """mean, Newey-West se, t, two-sided normal p"""
    x = np.asarray(x, float); n = len(x)
    mu = x.mean(); e = x - mu
    s = (e*e).sum()/n
    for k in range(1, min(L, n-1)+1):
        w = 1 - k/(L+1)
        s += 2*w*(e[k:]*e[:-k]).sum()/n
    s = max(s, 1e-18)
    se = math.sqrt(s/n)
    t = mu/se
    return mu, se, t, 2*(1-norm_cdf(abs(t)))

def nw_two_sample(x, y, L=NW_LAG):
    """NW difference-in-means test (independent samples)"""
    mx, sex, _, _ = nw_mean(x, L)
    my, sey, _, _ = nw_mean(y, L)
    se = math.sqrt(sex**2 + sey**2)
    t = (mx - my)/se
    return mx, my, t, 2*(1-norm_cdf(abs(t)))

def chow_test(x, y):
    """classic Chow F-test on mean shift (invalid under autocorr; reported as secondary)"""
    x = np.asarray(x, float); y = np.asarray(y, float)
    n1, n2 = len(x), len(y); k = 1
    pooled = np.concatenate([x, y])
    rss_p = ((pooled - pooled.mean())**2).sum()
    rss = ((x - x.mean())**2).sum() + ((y - y.mean())**2).sum()
    F = ((rss_p - rss)/k) / (rss/(n1+n2-2*k))
    # F(1, large) ~ chi2(1); p via normal approx of sqrt(F)
    return F, 2*(1-norm_cdf(math.sqrt(max(F, 0))))

def ann_stats(net_per, gross_per, years, in_pos=None):
    """annualized return on committed capital, Sharpe, NW t of per-period net"""
    tot_net = net_per.sum()
    ann_net = tot_net/years
    mu, se, t, p = nw_mean(net_per)
    sd = net_per.std(ddof=1)
    sharpe = mu/sd*math.sqrt(PPY) if sd > 0 else float('nan')
    tim = in_pos.mean() if in_pos is not None else 1.0
    return dict(ann_net=ann_net*100, t=t, p=p, sharpe=sharpe, tim=tim)

# ------------------------------------------------------------- load
f = pd.read_csv(f"{DATA}/binance_um_btcusdt_perp_funding.csv", parse_dates=["funding_time_utc"])
f = f.sort_values("funding_time_ms").reset_index(drop=True)
r = f["funding_rate"].values.astype(float)
ts = f["funding_time_utc"]
n = len(r)
dts = np.diff(f["funding_time_ms"].values)/3.6e6
assert np.allclose(dts, 8.0), f"funding grid not uniform 8h: {np.unique(dts)}"
years_full = n/PPY
print(f"funding sample: {ts.iloc[0]} .. {ts.iloc[-1]}  N={n} ({years_full:.2f}y)  grid=8h uniform OK")

# per-period streams
gross = r.copy()                      # carry per 8h on notional (committed capital basis)
net_h1 = gross - REB_PER              # always-on: rebalance drag every period

def regime_mask(a, b):
    return ((ts >= pd.Timestamp(a)) & (ts < pd.Timestamp(b))).values

REGIMES = [("full 2019-09..2026-11", "2019-01-01", "2027-01-01"),
           ("2024-01..2026-11", "2024-01-01", "2027-01-01"),
           ("post-cut 2025-09-18..", "2025-09-18", "2027-01-01")]

print("\n" + "="*86)
print("TASK 1: BASELINE ALWAYS-ON CARRY SIGNIFICANCE (net of costs)")
print("="*86)
print(f"cost model: round trip {RT_COST*100:.2f}% one-off (amortized over regime length) + "
      f"rebalance {REB_ANN*100:.2f}%/yr")
print(f"{'regime':<26}{'N':>6}{'yrs':>6}{'gross_ann%':>11}{'cost%/yr':>9}{'net_ann%':>9}"
      f"{'NW_t':>8}{'p':>10}{'Sharpe':>8}{'%pos':>7}")
base = {}
for lab, a, b in REGIMES:
    m = regime_mask(a, b)
    yrs = m.sum()/PPY
    gp, np_ = gross[m], net_h1[m] - RT_COST/m.sum()   # amortize round trip per period
    st = ann_stats(np_, gp, yrs)
    cost_ann = REB_ANN*100 + RT_COST*100/yrs
    base[lab] = st
    print(f"{lab:<26}{m.sum():>6}{yrs:>6.2f}{gp.mean()*PPY*100:>11.2f}{cost_ann:>9.2f}"
          f"{st['ann_net']:>9.2f}{st['t']:>8.2f}{st['p']:>10.2e}{st['sharpe']:>8.2f}"
          f"{(gp>0).mean()*100:>7.1f}")
# NW lag sensitivity
print("\nNW lag sensitivity (full sample / post-cut, t-stats):")
for L in [10, 30, 60, 90]:
    mf = regime_mask("2019-01-01", "2027-01-01"); mp = regime_mask("2025-09-18", "2027-01-01")
    tf = nw_mean(net_h1[mf] - RT_COST/mf.sum(), L)[2]
    tp = nw_mean(net_h1[mp] - RT_COST/mp.sum(), L)[2]
    print(f"  L={L:>3} ({L/3:>4.1f}d):  full t={tf:7.2f}   post-cut t={tp:7.2f}")

print("\n--- breakpoint test: post-cut vs pre segments (NW two-sample, bp/8h) ---")
mpost = regime_mask("2025-09-18", "2027-01-01")
for lab, a, b in [("pre recent 2024-01..2025-09-17", "2024-01-01", "2025-09-18"),
                  ("pre full 2019-09..2025-09-17", "2019-01-01", "2025-09-18")]:
    mpre = regime_mask(a, b)
    mx, my, t, p = nw_two_sample(gross[mpre], gross[mpost])
    F, pF = chow_test(gross[mpre], gross[mpost])
    print(f"  {lab}: pre={mx*1e4:7.4f}bp post={my*1e4:7.4f}bp  diff_t={t:7.2f} p={p:.2e}   "
          f"Chow F={F:8.1f} (p~{pF:.1e}, autocorr-invalidated, secondary)")

# monthly gross carry for regime eyeballing
mon = pd.Series(gross, index=ts).resample("ME").sum()*1e4
print("\nlast 18 monthly gross carry (bp):")
print(mon.tail(18).round(1).to_string())

# ------------------------------------------------------------- H3 state machine
print("\n" + "="*86)
print("TASK 2: H3 EXIT RULES vs H1 ALWAYS-ON  (exit after M consec neg, re-enter after K consec pos)")
print("="*86)

def simulate_h3(rr, M, K):
    """returns per-period net carry, in-position mask, n_cycles"""
    nn = len(rr)
    inpos = np.ones(nn, bool)
    state = 1                    # 1 = in, 0 = flat
    cneg = 0; cpos = 0
    cycles = 0
    i = 0
    # decision after observing payment i applies from period i+1
    inpos[0] = True
    for i in range(nn-1):
        if state == 1:
            cneg = cneg + 1 if rr[i] < 0 else 0
            if cneg >= M:
                state = 0; cpos = 0; cycles += 1
        else:
            cpos = cpos + 1 if rr[i] > 0 else 0
            if cpos >= K:
                state = 1; cneg = 0
        inpos[i+1] = (state == 1)
    net = np.where(inpos, rr - REB_PER, 0.0)
    # charge 0.075% at each exit and each re-entry (2 taker legs each)
    trans = np.diff(inpos.astype(int))
    net[1:][trans != 0] -= RT_COST/2
    return net, inpos, cycles

def simulate_h2(rr, T_bp, win=21):
    nn = len(rr)
    trail = pd.Series(rr).rolling(win).mean().values*1e4   # bp
    inpos = np.ones(nn, bool)
    inpos[1:nn] = trail[:nn-1] > T_bp    # decision from trailing mean known after payment i
    inpos[:win] = True                   # warm-up: in position
    net = np.where(inpos, rr - REB_PER, 0.0)
    trans = np.diff(inpos.astype(int))
    cycles = int((trans < 0).sum())
    net[1:][trans != 0] -= RT_COST/2
    return net, inpos, cycles

IS = regime_mask("2019-09-01", "2024-01-01")
OOS = regime_mask("2024-01-01", "2027-01-01")
print(f"IS: 2019-09..2023-12 N={IS.sum()} ({IS.sum()/PPY:.2f}y)   OOS: 2024-01..2026-11 N={OOS.sum()} ({OOS.sum()/PPY:.2f}y)")
print("costs: cycle = 0.15% (exit 2 legs + re-entry 2 legs); rebalance 0.30%/yr while in position")
bonf_z = norm_ppf(1 - 0.05/6/2)
print(f"Bonferroni 6 configs, two-sided 5%: |t| crit = {bonf_z:.2f}")

def eval_rule(net, mask, label):
    yrs = mask.sum()/PPY
    st = ann_stats(net[mask], gross[mask], yrs, None)
    # paired diff vs H1 on same mask
    d = net[mask] - net_h1[mask]
    md, se, td, pd_ = nw_mean(d)
    st.update(diff_bp=md*1e4*PPY/100, t_diff=td, p_diff=pd_)  # diff in %/yr units: mean bp/8h*PPY/1e4... careful
    st['diff_ann_pct'] = md*PPY*100
    return st

rows = []
h1_is = eval_rule(net_h1 - RT_COST/IS.sum(), IS, "H1")
h1_oos = eval_rule(net_h1 - RT_COST/OOS.sum(), OOS, "H1")
print(f"\n{'cfg':<10}{'ann_net%':>9}{'t':>7}{'SR':>6}{'cyc':>5}{'TiM%':>6}{'dAnn%':>7}{'t_diff':>8}{'p_diff':>10}   (IS)")
print(f"{'H1':<10}{h1_is['ann_net']:>9.2f}{h1_is['t']:>7.2f}{h1_is['sharpe']:>6.2f}{'-':>5}{100:>6.0f}"
      f"{0:>7.2f}{0:>8.2f}{1:>10.3f}")
h3_results = {}
for M in [2, 3, 5]:
    for K in [1, 3]:
        net, inp, cyc = simulate_h3(gross, M, K)
        st = eval_rule(net, IS, f"H3_M{M}K{K}")
        h3_results[(M, K)] = (net, inp, cyc, st)
        tim = inp[IS].mean()*100
        print(f"{'H3_M'+str(M)+'K'+str(K):<10}{st['ann_net']:>9.2f}{st['t']:>7.2f}{st['sharpe']:>6.2f}"
              f"{cyc:>5}{tim:>6.0f}{st['diff_ann_pct']:>7.2f}{st['t_diff']:>8.2f}{st['p_diff']:>10.4f}")

best = max(h3_results, key=lambda k: h3_results[k][3]['ann_net'])
net_b, inp_b, cyc_b, st_b = h3_results[best]
print(f"\nIS-selected config: H3_M{best[0]}K{best[1]} (highest IS net ann)")
print(f"IS superiority vs H1: diff={st_b['diff_ann_pct']:+.2f}%/yr  t={st_b['t_diff']:.2f}  "
      f"Bonferroni crit {bonf_z:.2f}  ->  {'SIGNIFICANT' if abs(st_b['t_diff'])>bonf_z else 'NOT significant'}")
print(f"\nOOS validation (single shot):")
print(f"{'cfg':<10}{'ann_net%':>9}{'t':>7}{'SR':>6}{'cyc':>5}{'TiM%':>6}{'dAnn%':>7}{'t_diff':>8}{'p_diff':>10}   (OOS)")
print(f"{'H1':<10}{h1_oos['ann_net']:>9.2f}{h1_oos['t']:>7.2f}{h1_oos['sharpe']:>6.2f}{'-':>5}{100:>6.0f}"
      f"{0:>7.2f}{0:>8.2f}{1:>10.3f}")
for (M, K), (net, inp, cyc, _) in h3_results.items():
    st = eval_rule(net, OOS, f"H3_M{M}K{K}")
    tim = inp[OOS].mean()*100
    tag = " <== IS-selected" if (M, K) == best else ""
    print(f"{'H3_M'+str(M)+'K'+str(K):<10}{st['ann_net']:>9.2f}{st['t']:>7.2f}{st['sharpe']:>6.2f}"
          f"{cyc:>5}{tim:>6.0f}{st['diff_ann_pct']:>7.2f}{st['t_diff']:>8.2f}{st['p_diff']:>10.4f}{tag}")

# ------------------------------------------------------------- H2 (only if H3 fails)
# H3 "passes" only if the IS-selected rule is significantly BETTER than H1 (t_diff > +crit).
h3_pass = st_b['t_diff'] > bonf_z
print("\n" + "="*86)
print("TASK 3: H2 ENTRY THRESHOLD (trailing 7d mean funding > T bp)")
print("="*86)
if h3_pass:
    print("H3 PASSED -> H2 skipped to preserve budget (per protocol).")
    h2_results = {}
else:
    print("H3 failed -> H2 executed as fallback. Trials counted for Deflated Sharpe: 6 (H3) + 3 (H2) + 1 (H1) = 10")
    h2_results = {}
    print(f"{'cfg':<10}{'ann_net%':>9}{'t':>7}{'SR':>6}{'cyc':>5}{'TiM%':>6}{'dAnn%':>7}{'t_diff':>8}{'p_diff':>10}   (IS)")
    for T in [0.5, 1.0, 2.0]:
        net, inp, cyc = simulate_h2(gross, T)
        st = eval_rule(net, IS, f"H2_T{T}")
        h2_results[T] = (net, inp, cyc, st)
        tim = inp[IS].mean()*100
        print(f"{('H2_T'+str(T)):<10}{st['ann_net']:>9.2f}{st['t']:>7.2f}{st['sharpe']:>6.2f}"
              f"{cyc:>5}{tim:>6.0f}{st['diff_ann_pct']:>7.2f}{st['t_diff']:>8.2f}{st['p_diff']:>10.4f}")
    if h2_results:
        bestT = max(h2_results, key=lambda k: h2_results[k][3]['ann_net'])
        print(f"\nIS-selected H2: T={bestT}bp;  OOS:")
        print(f"{'cfg':<10}{'ann_net%':>9}{'t':>7}{'SR':>6}{'cyc':>5}{'TiM%':>6}{'dAnn%':>7}{'t_diff':>8}{'p_diff':>10}   (OOS)")
        for T, (net, inp, cyc, _) in h2_results.items():
            st = eval_rule(net, OOS, f"H2_T{T}")
            tag = " <== IS-selected" if T == bestT else ""
            print(f"{('H2_T'+str(T)):<10}{st['ann_net']:>9.2f}{st['t']:>7.2f}{st['sharpe']:>6.2f}"
                  f"{cyc:>5}{inp[OOS].mean()*100:>6.0f}{st['diff_ann_pct']:>7.2f}{st['t_diff']:>8.2f}{st['p_diff']:>10.4f}{tag}")

    # Deflated Sharpe ratio (Bailey & Lopez de Prado) across trial Sharpes (IS)
    trial_sr = [h1_is['sharpe']] + [h3_results[k][3]['sharpe'] for k in h3_results] + \
               [h2_results[k][3]['sharpe'] for k in h2_results]
    T_obs = IS.sum()
    x = net_h1[IS] - RT_COST/IS.sum()
    daily = pd.Series(x).groupby(np.arange(len(x))//3).sum().values   # daily aggregation for moments
    sd = daily.std(ddof=1); mu = daily.mean()
    skew = float(((daily-mu)**3).mean()/sd**3); kurt = float(((daily-mu)**4).mean()/sd**4)
    sr_obs = mu/sd*math.sqrt(365)
    V = np.var(trial_sr, ddof=1)
    N_tr = len(trial_sr)
    g = 0.5772156649
    sr_star = math.sqrt(V)*((1-g)*norm_ppf(1-1/N_tr) + g*norm_ppf(1-1/(N_tr*math.e)))
    psr = norm_cdf((sr_obs - sr_star)*math.sqrt(len(daily)-1)/math.sqrt(1 - skew*sr_obs + (kurt-1)/4*sr_obs**2))
    print(f"\nDeflated Sharpe (H1 daily, IS): SR_obs(daily-ann)={sr_obs:.2f}  E[max SR | {N_tr} trials]={sr_star:.2f}")
    print(f"  skew={skew:.2f} kurt={kurt:.2f}  PSR(SR*)={psr:.4f}  -> {'PASSES' if psr>0.95 else 'FAILS'} 5% DSR hurdle")

# ------------------------------------------------------------- TASK 4: scenarios
print("\n" + "="*86)
print("TASK 4: 12-MONTH FORWARD NET CARRY — THREE SCENARIOS")
print("="*86)
mpost = regime_mask("2025-09-18", "2027-01-01")
mrec = regime_mask("2024-01-01", "2027-01-01")
g_post, g_rec = gross[mpost], gross[mrec]
se_post = nw_mean(g_post)[1]*PPY*100
se_rec = nw_mean(g_rec)[1]*PPY*100
net_post = g_post.mean()*PPY*100 - (REB_ANN + RT_COST)*100     # 12m deployment: full cost load
net_rec = g_rec.mean()*PPY*100 - (REB_ANN + RT_COST)*100
print(f"(a) post-cut regime persists: gross={g_post.mean()*PPY*100:.2f}%  net={net_post:.2f}%  "
      f"95%CI(net)~[{net_post-1.96*se_post:.2f}, {net_post+1.96*se_post:.2f}]")
print(f"(b) 2024-2026 blend:          gross={g_rec.mean()*PPY*100:.2f}%  net={net_rec:.2f}%  "
      f"95%CI(net)~[{net_rec-1.96*se_rec:.2f}, {net_rec+1.96*se_rec:.2f}]")
# bull conditioning: funding when price above 200d MA (recompute from 4h)
h = pd.read_csv(f"{DATA}/binance_um_btcusdt_perp_4h.csv", parse_dates=["open_time_utc"])
h = h.sort_values("open_time_ms").reset_index(drop=True)
h["ma200d"] = h["close"].rolling(200*6).mean()
px = h.set_index("open_time_utc")["close"]; ma = h.set_index("open_time_utc")["ma200d"]
bull = (ts.map(px) > ts.map(ma)).values
g_bull = gross[bull & ~np.isnan(ts.map(ma).values.astype(float))]
g_2021 = gross[regime_mask("2021-01-01", "2022-01-01")]
net_bull = g_bull.mean()*PPY*100 - (REB_ANN + RT_COST)*100
net_2021 = g_2021.mean()*PPY*100 - (REB_ANN + RT_COST)*100
print(f"(c) bull regime: hist bull-cond gross={g_bull.mean()*PPY*100:.2f}% (N={len(g_bull)})  net={net_bull:.2f}%   "
      f"| 2021-style: gross={g_2021.mean()*PPY*100:.2f}%  net={net_2021:.2f}%")

# regime persistence statistics (data-grounded probabilities)
roll90 = pd.Series(gross, index=ts).rolling(270).mean()*PPY*100
low = (roll90 < 5.0).values   # "low regime": rolling 90d ann < 5%
runs_low = []
i = 0
valid = ~np.isnan(roll90.values)
while i < n:
    if valid[i] and low[i]:
        j = i
        while j < n and valid[j] and low[j]:
            j += 1
        runs_low.append((ts.iloc[i], (j-i)/3/30.44))  # months
        i = j
    else:
        i += 1
print(f"\nregime persistence stats (rolling-90d ann carry < 5% episodes):")
print(f"  share of valid history in low regime: {np.nanmean(low):.1%}")
for s, m in runs_low:
    print(f"  episode start {s.date()}  duration {m:.1f} months")
durs = np.array([m for _, m in runs_low if m > 0.3])
if len(durs):
    print(f"  durations>~10d: median {np.median(durs):.1f}m  max {durs.max():.1f}m  "
          f"P(duration>=12m | episode) = {(durs>=12).mean():.2f} (N={len(durs)})")
print(f"  post-cut regime age at sample end: {(ts.iloc[-1]-CUT).days/30.44:.1f} months and still low")

# ------------------------------------------------------------- TASK 5: tails
print("\n" + "="*86)
print("TASK 5: TAIL & STRESS STATISTICS")
print("="*86)
neg = gross < 0
runs = []
i = 0
while i < n:
    if neg[i]:
        j = i
        while j < n and neg[j]:
            j += 1
        runs.append(gross[i:j].sum()*1e4)   # bp, negative
        i = j
    else:
        i += 1
runs = np.array(runs)
loss = -runs
print(f"negative runs: N={len(runs)}  cumulative loss per run (bp): "
      f"median={np.median(loss):.2f}  p90={np.quantile(loss,.9):.2f}  p95={np.quantile(loss,.95):.2f}  "
      f"p99={np.quantile(loss,.99):.2f}  max={loss.max():.2f}")
# GPD (POT) on run losses over threshold u
for u in [5.0, 10.0, 20.0]:
    exc = loss[loss > u] - u
    if len(exc) < 10:
        print(f"  u={u:.0f}bp: only {len(exc)} exceedances, skip"); continue
    m, v = exc.mean(), exc.var(ddof=1)
    xi = max(0.5*(1 - m*m/v), -0.49)     # method of moments, bounded
    beta = m*(1-xi)
    Nu, N = len(exc), len(loss)
    q99 = u + beta/xi*(((Nu/N)/0.01)**xi - 1) if abs(xi) > 1e-6 else u + beta*math.log((Nu/N)/0.01)
    q995 = u + beta/xi*(((Nu/N)/0.005)**xi - 1) if abs(xi) > 1e-6 else u + beta*math.log((Nu/N)/0.005)
    print(f"  GPD u={u:.0f}bp: Nu={Nu}  xi={xi:.3f} beta={beta:.2f}  -> Q99={q99:.1f}bp  Q99.5={q995:.1f}bp")
# single-period negative tail
negmag = -gross[gross < 0]*1e4
print(f"single-period negative funding (bp): N={len(negmag)}  p95={np.quantile(negmag,.95):.2f}  "
      f"p99={np.quantile(negmag,.99):.2f}  max={negmag.max():.2f}")
negmag_post = -(gross[mpost])[gross[mpost] < 0]*1e4
print(f"  post-cut only: N={len(negmag_post)}  p95={np.quantile(negmag_post,.95):.2f}  "
      f"p99={np.quantile(negmag_post,.99):.2f}  max={negmag_post.max():.2f}")
# stress: month at -1.5bp every period
print(f"\nstress: every 8h at -1.5bp (post-cut worst observed level): "
      f"monthly drag = {-1.5*90:.0f}bp = {-1.5*90/100:.2f}% of notional/month")
mon_all = pd.Series(gross, index=ts).resample("ME").sum()*1e4
w5 = mon_all.nsmallest(5)
print("worst-5 historical calendar months (bp):")
for d0, v0 in w5.items():
    print(f"  {d0.date()}: {v0:.1f}bp ({v0/100:.2f}%)")

# ------------------------------------------------------------- TASK 6: correlations
print("\n" + "="*86)
print("TASK 6: PORTFOLIO CORRELATIONS (monthly aggregation)")
print("="*86)
carry_m = pd.Series(gross, index=ts).resample("ME").sum()
close4 = h.set_index("open_time_utc")["close"]
btc_m = close4.resample("ME").last().pct_change()
cm = pd.concat([carry_m.rename("carry"), btc_m.rename("btc")], axis=1).dropna()
print(f"corr(carry, BTC buy&hold) monthly: {cm['carry'].corr(cm['btc']):.3f}  (N={len(cm)} months)")
cm24 = cm[cm.index >= "2024-01-01"]
print(f"  2024+ only: {cm24['carry'].corr(cm24['btc']):.3f}  (N={len(cm24)})")
# 8h level: funding vs perp 8h return
r8 = close4.resample("8h").last().pct_change()
c8 = pd.concat([pd.Series(gross, index=ts).rename("carry"), r8.rename("btc8h")], axis=1).dropna()
print(f"corr(funding, perp 8h return): {c8['carry'].corr(c8['btc8h']):.3f}  (N={len(c8)})")
# round-1 vetoed strategy equity (daily -> monthly)
try:
    e1 = pd.read_csv("research/backtest_equity_main.csv", parse_dates=["date"])
    e1["date"] = e1["date"].dt.tz_localize(None)
    e1m = e1.set_index("date")["equity"].resample("ME").last().pct_change()
    c1 = pd.concat([carry_m.rename("carry"), e1m.rename("r1")], axis=1).dropna()
    print(f"corr(carry, round-1 breakout equity) monthly: {c1['carry'].corr(c1['r1']):.3f}  (N={len(c1)})")
except Exception as ex:
    print(f"round-1 equity correlation not executed: {ex}")
# round-2 vetoed strategy trades (R_net summed by exit month)
try:
    t2 = pd.read_csv("research/qr_f2_oos_trades_frozen.csv", parse_dates=["exit_ts"])
    r2m = t2.set_index("exit_ts")["R_net"].resample("ME").sum()
    c2 = pd.concat([carry_m.rename("carry"), r2m.rename("r2")], axis=1).dropna()
    print(f"corr(carry, round-2 strategy R stream) monthly: {c2['carry'].corr(c2['r2']):.3f}  (N={len(c2)})")
except Exception as ex:
    print(f"round-2 R-stream correlation not executed: {ex}")
print("round-3 (mr3): no return stream artifact available (config-level stats only) -> not executed")

print("\n--- per-year gross carry summary (reference) ---")
fy = pd.DataFrame({"r": gross}, index=ts)
for y, g0 in fy.groupby(fy.index.year):
    rr = g0["r"].values
    print(f"  {y}: N={len(rr):>5}  gross_ann={rr.mean()*PPY*100:>6.2f}%  %pos={(rr>0).mean()*100:>5.1f}  "
          f"min={rr.min()*1e4:>6.2f}bp  max={rr.max()*1e4:>6.2f}bp")
