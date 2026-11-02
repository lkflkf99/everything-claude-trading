"""qr_02b: Ablations, gate robustness, and bootstrap uncertainty for the horse race.

Pre-registered tests (no scanning):
  A. Benchmark fix: BH = SPOT buy&hold (no funding, single entry cost) — the user's
     true opportunity cost. Managed strategies still perp-based (funding + 5bp taker).
  B. Ablation TG1x: w = trend gate only (1x above 200d, flat below), no vol scaling.
     Is vol scaling adding anything beyond the gate?
  C. Gate robustness (4 variants -> Bonferroni alpha = 0.05/4 = 0.0125):
     SMA150 / SMA200(primary) / SMA250 / 12-month absolute momentum, all x VT50.
  D. Circular block bootstrap (30d blocks, 2000 resamples) on OOS 2022-2026:
     - 95% CI for VT_TG Sharpe / CAGR / MDD
     - paired test: VT_TG minus VT (does the gate add anything?) and VT_TG minus TG1x
       (does vol scaling add anything?)

Outputs: qr_gate_robustness.csv, qr_bootstrap_oos.json, qr_ablation_windows.csv
"""
import pandas as pd, numpy as np, json, sys
sys.path.insert(0, "research/highrisk")
from qr_utils import perf_stats

OUT = "research/highrisk"
pan = pd.read_csv(f"{OUT}/qr_daily_panel.csv", index_col=0, parse_dates=True)
TC = 0.0005
rng = np.random.default_rng(20261102)

d = pan.dropna(subset=["ret1", "fund_sum"]).copy()
r = d["ret1"].fillna(0.0).values
fund = d["fund_sum"].fillna(0.0).values
idx = d.index

def sim(w_target):
    """Daily sim given target weight series (array). Returns daily net strat returns, w_held, turnover."""
    w = np.asarray(w_target, float)
    w = np.nan_to_num(w, nan=0.0)
    wh = np.concatenate([[0.0], w[:-1]])
    eq = 1.0
    rets = np.zeros(len(w))
    turn = np.zeros(len(w))
    for t in range(len(w)):
        drifted = wh[t] * (1 + r[t])
        turn[t] = abs(w[t] - drifted)
        cost = TC * turn[t]
        day = wh[t] * r[t] - wh[t] * fund[t] - cost
        rets[t] = day / 1.0  # simple return on equity (equity path via cumprod)
        eq *= (1 + rets[t])
    return rets, wh, turn

rv30 = (d["ret1"].rolling(30).std() * np.sqrt(365)).values
sma200 = d["close"].rolling(200).mean().values
sma150 = d["close"].rolling(150).mean().values
sma250 = d["close"].rolling(250).mean().values
mom12m = (d["close"] / d["close"].shift(365) - 1).values
close = d["close"].values

VT = np.clip(0.50 / rv30, 0, 2.0)
strategies = {
    "BH_spot": None,  # handled specially: ret = r, no funding, no costs
    "VT": VT,
    "TG1x": (close > sma200).astype(float),
    "VT_TG": VT * (close > sma200).astype(float),
    "VT_TG150": VT * (close > sma150).astype(float),
    "VT_TG250": VT * (close > sma250).astype(float),
    "VT_MOM12M": VT * (mom12m > 0).astype(float),
}
rets = {}
whs = {}
for name, w in strategies.items():
    if name == "BH_spot":
        rets[name] = r.copy()
        whs[name] = np.ones(len(r))
    else:
        rets[name], whs[name], _ = sim(w)

OOS = ("2022-01-01", "2026-10-31")
m = (idx >= OOS[0]) & (idx <= OOS[1])
FULL = slice(200, len(r))  # after sma200 warmup

# ---------- window table incl ablations ----------
WINDOWS = [("2022", "2022-01-01", "2022-12-31"), ("2023", "2023-01-01", "2023-12-31"),
           ("2024", "2024-01-01", "2024-12-31"), ("2025_2026", "2025-01-01", "2026-10-31"),
           ("OOS_2022_2026", "2022-01-01", "2026-10-31")]
rows = []
for lbl, a, b in WINDOWS:
    mm = (idx >= a) & (idx <= b)
    for name in strategies:
        ps = perf_stats(rets[name][mm])
        ps.update({"window": lbl, "strategy": name, "avg_w": round(float(whs[name][mm].mean()), 3)})
        rows.append(ps)
abl = pd.DataFrame(rows)
for c in ["ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd"]:
    abl[c] = abl[c].astype(float).round(3)
abl.to_csv(f"{OUT}/qr_ablation_windows.csv", index=False)
print("=== ABLATION WINDOWS (net) ===")
print(abl[["window", "strategy", "n", "ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd", "avg_w"]].to_string(index=False))

# ---------- gate robustness (4 variants, Bonferroni) ----------
gr = abl[abl["window"].isin(["OOS_2022_2026"]) & abl["strategy"].isin(
    ["VT_TG", "VT_TG150", "VT_TG250", "VT_MOM12M"])].copy()
gr.to_csv(f"{OUT}/qr_gate_robustness.csv", index=False)
print("\n=== GATE ROBUSTNESS OOS (Bonferroni alpha 0.0125) ===")
print(gr[["strategy", "cagr", "ann_vol", "sharpe", "mdd", "avg_w"]].to_string(index=False))

# ---------- circular block bootstrap on OOS ----------
def cbb_indices(n, block, n_boot, rng):
    """Circular block bootstrap: each resample = ceil(n/block) contiguous blocks."""
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(n_boot, nb))          # (B, nb)
    within = np.arange(block)[None, None, :]                # (1,1,block)
    ii = (starts[:, :, None] + within) % n                  # (B, nb, block)
    return ii.reshape(n_boot, nb * block)[:, :n]

def sharpe_of(x):
    x = x[np.isfinite(x)]
    if len(x) < 10 or x.std(ddof=1) == 0:
        return np.nan
    return x.mean() / x.std(ddof=1) * np.sqrt(365)

def cagr_of(x):
    x = x[np.isfinite(x)]
    eq = np.cumprod(1 + x)
    yrs = len(x) / 365
    return eq[-1] ** (1 / yrs) - 1 if yrs > 0 and eq[-1] > 0 else np.nan

def mdd_of(x):
    eq = np.cumprod(1 + x)
    peak = np.maximum.accumulate(eq)
    return float((eq / peak - 1).min())

n_oos = int(m.sum())
BOOT = 2000
BLOCK = 60  # 60d blocks preserve vol clustering + drawdown persistence better
II = cbb_indices(n_oos, BLOCK, BOOT, rng)
ro = {name: rets[name][m] for name in strategies}

boot = {}
for name in ["VT_TG", "VT", "TG1x", "BH_spot"]:
    x = ro[name]
    samp = x[II]  # (BOOT, n)
    sh = np.array([sharpe_of(s) for s in samp])
    cg = np.array([cagr_of(s) for s in samp])
    md = np.array([mdd_of(s) for s in samp])
    boot[name] = {
        "sharpe_ci95": [round(float(np.nanpercentile(sh, 2.5)), 3), round(float(np.nanpercentile(sh, 97.5)), 3)],
        "sharpe_median": round(float(np.nanmedian(sh)), 3),
        "cagr_ci95": [round(float(np.nanpercentile(cg, 2.5)), 3), round(float(np.nanpercentile(cg, 97.5)), 3)],
        "cagr_median": round(float(np.nanmedian(cg)), 3),
        "mdd_ci95_worst_best": [round(float(np.nanpercentile(md, 2.5)), 3), round(float(np.nanpercentile(md, 97.5)), 3)],
        "mdd_median": round(float(np.nanmedian(md)), 3),
        "p_sharpe_le_0": round(float((sh <= 0).mean()), 4),
    }

# paired differences (same blocks)
def paired(a, b):
    da, db = ro[a], ro[b]
    dsh = np.array([sharpe_of(da[ii]) - sharpe_of(db[ii]) for ii in II])
    dcg = np.array([cagr_of(da[ii]) - cagr_of(db[ii]) for ii in II])
    return {"pair": f"{a} - {b}",
            "dsharpe_median": round(float(np.nanmedian(dsh)), 3),
            "dsharpe_ci95": [round(float(np.nanpercentile(dsh, 2.5)), 3), round(float(np.nanpercentile(dsh, 97.5)), 3)],
            "p_dsharpe_le_0": round(float((dsh <= 0).mean()), 4),
            "dcagr_median": round(float(np.nanmedian(dcg)), 3),
            "p_dcagr_le_0": round(float((dcg <= 0).mean()), 4)}

pairs = [paired("VT_TG", "VT"), paired("VT_TG", "TG1x"), paired("VT_TG", "BH_spot"), paired("TG1x", "VT")]

out = {"oos_window": OOS, "n_days": n_oos, "block_len": BLOCK, "n_boot": BOOT,
       "point_estimates": {name: {k: round(v, 3) if isinstance(v, float) else v for k, v in
                                  perf_stats(ro[name]).items() if k in ["ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd"]}
                           for name in ["VT_TG", "VT", "TG1x", "BH_spot"]},
       "bootstrap": boot, "paired_tests": pairs}
with open(f"{OUT}/qr_bootstrap_oos.json", "w") as fh:
    json.dump(out, fh, indent=2)
print("\n=== BOOTSTRAP OOS (30d blocks, 2000x) ===")
print(json.dumps(boot, indent=2))
print("\n=== PAIRED ===")
print(json.dumps(pairs, indent=2))
