"""bt_02: 60d-block bootstrap x2000 for A0..A3, FULL and OOS windows.

Mirrors QR's bootstrap design (qr_bootstrap_oos.json: block_len=60, n_boot=2000,
OOS 2022-01-01..2026-10-31). Paired by construction: identical block draws feed
every arm in a window. Reports per arm x window: CAGR/Sharpe CI95+median,
MDD median + CI95 (worst..best); paired vs A0: dMDD (arm - A0; positive =
shallower drawdown), dCAGR, dSharpe medians + p(d <= 0).

Selection rule input: 'bootstrap MDD median improves >=5pp vs A0' evaluated as
median(MDD_arm) - median(MDD_A0) per window; paired median(dMDD) also reported.

Outputs: bt_bootstrap.json
"""
import pandas as pd, numpy as np, json, sys
sys.path.insert(0, "research/highrisk")
from bt_common import OUT

daily = pd.read_csv(f"{OUT}/bt_daily.csv", index_col=0, parse_dates=True)
idx = daily.index
ARMS = ["A0_baseline", "A1_VB", "A2_TS30", "A3_VB_TS"]
BLOCK = 60
NBOOT = 2000
rng = np.random.default_rng(12345)


def boot_metrics(ret_mat):
    """ret_mat: (B, n) resampled daily net returns -> (B,3): cagr, sharpe, mdd."""
    B, n = ret_mat.shape
    eq = np.cumprod(1.0 + ret_mat, axis=1)
    yrs = n / 365.0
    cagr = np.sign(eq[:, -1]) * np.abs(eq[:, -1]) ** (1.0 / yrs) - 1.0
    mu = ret_mat.mean(axis=1) * 365.0
    sd = ret_mat.std(axis=1, ddof=1) * np.sqrt(365.0)
    sharpe = np.where(sd > 0, mu / sd, np.nan)
    peak = np.maximum.accumulate(eq, axis=1)
    mdd = (eq / peak - 1.0).min(axis=1)
    return cagr, sharpe, mdd


def run_window(label, mask):
    n = int(mask.sum())
    nb = int(np.ceil(n / BLOCK))
    # (NBOOT, nb) block starts, uniform in [0, n-BLOCK]... allow wrap-free starts
    starts = rng.integers(0, n - BLOCK + 1, size=(NBOOT, nb))
    # build index matrix (NBOOT, n) via broadcasting
    offs = np.arange(BLOCK)
    blocks = starts[:, :, None] + offs[None, None, :]      # (NBOOT, nb, BLOCK)
    bidx = blocks.reshape(NBOOT, nb * BLOCK)[:, :n]        # (NBOOT, n)
    rets = {a: daily[f"ret_{a}"].values[mask] for a in ARMS}
    res = {}
    mats = {}
    for a in ARMS:
        cagr, sharpe, mdd = boot_metrics(rets[a][bidx])
        mats[a] = (cagr, sharpe, mdd)
        res[a] = {
            "cagr_median": float(np.median(cagr)),
            "cagr_ci95": [float(np.percentile(cagr, 2.5)), float(np.percentile(cagr, 97.5))],
            "sharpe_median": float(np.median(sharpe)),
            "sharpe_ci95": [float(np.percentile(sharpe, 2.5)), float(np.percentile(sharpe, 97.5))],
            "mdd_median": float(np.median(mdd)),
            "mdd_ci95_worst_best": [float(np.percentile(mdd, 2.5)), float(np.percentile(mdd, 97.5))],
        }
    paired = []
    for a in ARMS[1:]:
        dmdd = mats[a][2] - mats["A0_baseline"][2]      # >0 = shallower dd
        dcagr = mats[a][0] - mats["A0_baseline"][0]
        dshp = mats[a][1] - mats["A0_baseline"][1]
        paired.append({
            "pair": f"{a} - A0_baseline",
            "dmdd_median": float(np.median(dmdd)),
            "dmdd_ci95": [float(np.percentile(dmdd, 2.5)), float(np.percentile(dmdd, 97.5))],
            "p_dmdd_le_0": float((dmdd <= 0).mean()),
            "dcagr_median": float(np.median(dcagr)),
            "p_dcagr_le_0": float((dcagr <= 0).mean()),
            "dsharpe_median": float(np.nanmedian(dshp)),
            "p_dsharpe_le_0": float(np.nanmean(dshp <= 0)),
        })
    return {"n_days": n, "block_len": BLOCK, "n_boot": NBOOT,
            "per_arm": res, "paired_vs_A0": paired}


out = {"seed": 12345, "windows": {}}
m_full = np.zeros(len(idx), bool); m_full[200:] = True
m_full &= (idx >= "2020-01-01") & (idx <= "2026-10-31")
m_oos = (idx >= "2022-01-01") & (idx <= "2026-10-31")
for lbl, m in [("FULL_2020H2_2026", m_full), ("OOS_2022_2026", m_oos)]:
    out["windows"][lbl] = run_window(lbl, m.values if hasattr(m, "values") else m)

# selection-rule summary helper: difference of medians
sel = {}
for lbl, w in out["windows"].items():
    sel[lbl] = {a: round(100 * (w["per_arm"][a]["mdd_median"] -
                                  w["per_arm"]["A0_baseline"]["mdd_median"]), 2)
                for a in ARMS[1:]}
out["mdd_median_improvement_pp_vs_A0"] = sel

with open(f"{OUT}/bt_bootstrap.json", "w") as fh:
    json.dump(out, fh, indent=2)
print(json.dumps(out, indent=2))
