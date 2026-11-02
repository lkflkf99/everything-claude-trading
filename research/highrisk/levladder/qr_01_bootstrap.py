"""qr_01: paired 60d-block bootstrap (2000 reps, seed 12345) of the leverage arms.

Design mirrors bt_02_bootstrap.py EXACTLY (block=60, n_boot=2000, seed=12345,
same window masks, same rng consumption order: FULL then OOS) so that:
  (a) all arms share identical block draws within a window (paired), and
  (b) the shipped A1_VB series (bt_daily ret_A1_VB, QR-parity accounting) run
      through this harness must reproduce bt_verdict.json e_bootstrap numbers
      bit-for-bit -> harness validation.

Arm return series: daily close-to-close net returns derived from the analyst's
validated book engines (book_*.json 'equity' curves; 1x engine parity vs the
shipped book: 11bp/yr, see validation_1x.json). Books end 2026-10-30; panel ends
2026-10-31 -> equity ffilled one day (one zero-return day out of 2295, noted).

LIMITATION (stated for downstream agents): bootstrap resamples close-to-close
daily returns. It CANNOT represent intraday (5m mark) liquidation paths; the
analyst's 5m sims cover that channel (no kills <=2x on the realized path).

Outputs: qr_daily.csv (aligned daily returns per arm), qr_bootstrap.json.
"""
import pandas as pd, numpy as np, json, os

HR = "research/highrisk"
OUT = "research/highrisk/levladder"
BLOCK = 60
NBOOT = 2000
SEED = 12345

# ---------------------------------------------------------------- return panel
daily = pd.read_csv(f"{HR}/bt_daily.csv", index_col=0, parse_dates=True)
daily.index = daily.index.normalize()
idx = daily.index

BOOK_ARMS = {
    "const_1.0": "book_const_1.0.json",
    "const_1.5": "book_const_1.5.json",
    "strategist_1.5_rv60": "book_strategist_1.5_rv60.json",
    "const_2.0": "book_const_2.0.json",
    "const_3.0": "book_const_3.0.json",
    # the 9-variant conditional family at 1.5x (task 3)
    "L1.5_rv50": "book_L1.5_rv50.json",
    "L1.5_rv50_dd15": "book_L1.5_rv50_dd15.json",
    "L1.5_rv50_dd20": "book_L1.5_rv50_dd20.json",
    "L1.5_rv60_dd15": "book_L1.5_rv60_dd15.json",
    "L1.5_rv60_dd20": "book_L1.5_rv60_dd20.json",
    "L1.5_rv70": "book_L1.5_rv70.json",
    "L1.5_rv70_dd15": "book_L1.5_rv70_dd15.json",
    "L1.5_rv70_dd20": "book_L1.5_rv70_dd20.json",
}

rets = {}
notes = []
for name, fn in BOOK_ARMS.items():
    b = json.load(open(f"{OUT}/{fn}"))
    eq = pd.Series({pd.Timestamp(d): float(v) for d, v in b["equity"]}).sort_index()
    if name == "strategist_1.5_rv60":
        eq60 = pd.Series({pd.Timestamp(d): float(v) for d, v in
                          json.load(open(f"{OUT}/book_L1.5_rv60.json"))["equity"]}).sort_index()
        assert eq.equals(eq60), "strategist_1.5_rv60 != L1.5_rv60"
        notes.append("strategist_1.5_rv60 == L1.5_rv60 (identical equity curves); "
                     "spec-§8 arm is a member of the analyst's 9-variant scan.")
    eq = eq.reindex(idx).ffill()
    assert eq.isna().sum() <= 200, f"{name}: {eq.isna().sum()} leading NaNs unexpected"
    r = eq.pct_change().fillna(0.0)
    rets[name] = r.values
# reproduction-check series: shipped A1_VB (QR-parity), same as bt_02 input
rets["shipped_A1_VB_qr_parity"] = daily["ret_A1_VB"].values

qr_daily = pd.DataFrame(rets, index=idx)
qr_daily.to_csv(f"{OUT}/qr_daily.csv")

MAIN_ARMS = ["const_1.0", "const_1.5", "strategist_1.5_rv60", "const_2.0", "const_3.0",
             "shipped_A1_VB_qr_parity"]

# ---------------------------------------------------------------- metrics
def boot_metrics(ret_mat):
    """(B,n) resampled daily net returns -> cagr, sharpe, mdd, calmar per rep."""
    B, n = ret_mat.shape
    eq = np.cumprod(1.0 + ret_mat, axis=1)
    yrs = n / 365.0
    cagr = np.sign(eq[:, -1]) * np.abs(eq[:, -1]) ** (1.0 / yrs) - 1.0
    mu = ret_mat.mean(axis=1) * 365.0
    sd = ret_mat.std(axis=1, ddof=1) * np.sqrt(365.0)
    sharpe = np.where(sd > 0, mu / sd, np.nan)
    peak = np.maximum.accumulate(eq, axis=1)
    mdd = (eq / peak - 1.0).min(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        calmar = np.where(mdd < 0, cagr / np.abs(mdd), np.nan)
    return cagr, sharpe, mdd, calmar


def realized(r):
    """Full-sample realized metrics on a daily-return array."""
    r = np.asarray(r)
    eq = np.cumprod(1.0 + r)
    yrs = len(r) / 365.0
    cagr = float(eq[-1] ** (1.0 / yrs) - 1.0) if eq[-1] > 0 else -1.0
    sharpe = float(r.mean() / r.std(ddof=1) * np.sqrt(365.0)) if r.std(ddof=1) > 0 else np.nan
    mdd = float((eq / np.maximum.accumulate(eq) - 1.0).min())
    return {"cagr": cagr, "sharpe": sharpe, "mdd": mdd,
            "calmar": cagr / abs(mdd) if mdd < 0 else np.nan, "n_days": int(len(r))}


def summarize(arr):
    return {"median": float(np.nanmedian(arr)),
            "ci95": [float(np.nanpercentile(arr, 2.5)), float(np.nanpercentile(arr, 97.5))]}


rng = np.random.default_rng(SEED)
out = {"seed": SEED, "block_len": BLOCK, "n_boot": NBOOT,
       "design": "paired 60d block bootstrap, identical draws across arms; "
                 "mirrors bt_02_bootstrap.py (rng consumed FULL then OOS)",
       "notes": notes, "windows": {}}

for lbl, m in [("FULL_2020H2_2026",
                (np.arange(len(idx)) >= 200) & (idx >= "2020-01-01") & (idx <= "2026-10-31")),
               ("OOS_2022_2026",
                (idx >= "2022-01-01") & (idx <= "2026-10-31"))]:
    n = int(m.sum())
    nb = int(np.ceil(n / BLOCK))
    starts = rng.integers(0, n - BLOCK + 1, size=(NBOOT, nb))
    offs = np.arange(BLOCK)
    bidx = (starts[:, :, None] + offs[None, None, :]).reshape(NBOOT, nb * BLOCK)[:, :n]
    mats, res, real = {}, {}, {}
    for a in MAIN_ARMS:
        r = rets[a][m]
        cagr, sharpe, mdd, calmar = boot_metrics(r[bidx])
        mats[a] = (cagr, sharpe, mdd, calmar)
        res[a] = {"cagr": summarize(cagr), "sharpe": summarize(sharpe),
                  "mdd": summarize(mdd), "calmar": summarize(calmar),
                  "p_mdd_worse_than_50pct": float((mdd <= -0.50).mean()),
                  "p_mdd_worse_than_60pct": float((mdd <= -0.60).mean())}
        real[a] = realized(r)
    paired = []
    for a in MAIN_ARMS:
        if a in ("const_1.0", "shipped_A1_VB_qr_parity"):
            continue
        d = {}
        for i, k in enumerate(["cagr", "sharpe", "mdd", "calmar"]):
            dd = mats[a][i] - mats["const_1.0"][i]
            d[f"d{k}_median"] = float(np.nanmedian(dd))
            d[f"d{k}_ci95"] = [float(np.nanpercentile(dd, 2.5)), float(np.nanpercentile(dd, 97.5))]
            d[f"p_d{k}_le_0"] = float(np.nanmean(dd <= 0))
        paired.append({"pair": f"{a} - const_1.0", **d})
    # direct pre-registered comparison: conditional vs constant at 1.5x
    dd_pair = {}
    for i, k in enumerate(["cagr", "sharpe", "mdd", "calmar"]):
        dd = mats["strategist_1.5_rv60"][i] - mats["const_1.5"][i]
        dd_pair[f"d{k}_median"] = float(np.nanmedian(dd))
        dd_pair[f"d{k}_ci95"] = [float(np.nanpercentile(dd, 2.5)), float(np.nanpercentile(dd, 97.5))]
        dd_pair[f"p_d{k}_le_0"] = float(np.nanmean(dd <= 0))
    paired.append({"pair": "strategist_1.5_rv60 - const_1.5", **dd_pair})
    out["windows"][lbl] = {"n_days": n, "per_arm_boot": res, "per_arm_realized": real,
                           "paired": paired}

# ---------------------------------------------------------------- validation
btv = json.load(open(f"{HR}/bt_verdict.json"))["e_bootstrap"]
chk = []
for lbl, key in [("FULL_2020H2_2026", "FULL_per_arm"), ("OOS_2022_2026", "OOS_per_arm")]:
    got = out["windows"][lbl]["per_arm_boot"]["shipped_A1_VB_qr_parity"]
    want = btv[key]["A1_VB"]
    for m_, g, w in [("cagr_median", got["cagr"]["median"], want["cagr_median"]),
                     ("sharpe_median", got["sharpe"]["median"], want["sharpe_median"]),
                     ("mdd_median", got["mdd"]["median"], want["mdd_median"])]:
        chk.append({"window": lbl, "metric": m_, "got": g, "want": w,
                    "pass": bool(abs(g - w) < 1e-12)})
out["harness_validation_vs_bt_verdict"] = {
    "checks": chk, "all_pass": bool(all(c["pass"] for c in chk)),
    "meaning": "shipped_A1_VB_qr_parity through this harness reproduces "
               "bt_verdict.json e_bootstrap medians bit-for-bit -> harness and "
               "design are identical to the shipped 1x bootstrap."}

with open(f"{OUT}/qr_bootstrap.json", "w") as fh:
    json.dump(out, fh, indent=2)
print("harness validation all_pass:", out["harness_validation_vs_bt_verdict"]["all_pass"])
for lbl in out["windows"]:
    w = out["windows"][lbl]
    print(f"\n=== {lbl} (n={w['n_days']}) ===")
    for a in MAIN_ARMS:
        r = w["per_arm_boot"][a]
        print(f"{a:26s} realized CAGR {100*w['per_arm_realized'][a]['cagr']:7.2f}%  "
              f"MDD {100*w['per_arm_realized'][a]['mdd']:7.2f}%  "
              f"Sharpe {w['per_arm_realized'][a]['sharpe']:.3f} | "
              f"boot MDD med {100*r['mdd']['median']:7.2f}%  "
              f"CI95 [{100*r['mdd']['ci95'][0]:7.2f},{100*r['mdd']['ci95'][1]:7.2f}]  "
              f"P(MDD<-50%) {r['p_mdd_worse_than_50pct']:.3f}")
    for p in w["paired"]:
        print(f"  paired {p['pair']:38s} dCAGR med {100*p['dcagr_median']:+6.2f}pp "
              f"p={p['p_dcagr_le_0']:.4f} | dSharpe med {p['dsharpe_median']:+.3f} "
              f"p={p['p_dsharpe_le_0']:.4f} | dMDD med {100*p['dmdd_median']:+6.2f}pp "
              f"p={p['p_dmdd_le_0']:.4f}")
