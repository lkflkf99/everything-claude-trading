"""qr_02: selection-bias correction for the analyst's 9-variant conditional scan (1.5x).

The analyst scanned 9 conditional arms (rv10 in {50,60,70} x dd-overlay {none,15,20})
and quoted the best (L1.5_rv50, realized MDD -49.77% vs const_1.5 -59.53%). That best
is a post-hoc max over 9 correlated trials -> its naive p-value is invalid.

Correction stack (all on the SAME paired block draws; FULL window; fresh rng(12345)
-> identical starts to qr_01's FULL run, so const_1.5 numbers tie out):
  1. naive paired p per variant: P(dmdd <= 0), dmdd = mdd_variant - mdd_const_1.5
  2. Bonferroni x 9
  3. Holm step-down
  4. Romano-Wolf / White reality-check single-step max-statistic:
       Z_b = max_k ( dmdd_k,b - dmdd_k,obs );  adj_p_k = P( Z_b >= dmdd_k,obs )
     with dmdd_k,obs = realized full-sample improvement. This is THE corrected p-value
     for "the best variant beats constant 1.5x on MDD".
  5. E[max under null] = mean(Z_b): the best-of-9 improvement you would expect on
     average if every variant's true effect were zero.

Pre-registered arm: strategist_1.5_rv60 == spec STRATEGY_SPEC_v1.md section 8
(L=1.5 iff state=1 AND vb_state=ON AND rv10<=0.60, documented 2026-11-02 BEFORE the
ladder results existed). It is reported STANDALONE with its uncorrected p vs const_1.5
(from qr_01). Note: it is also a member of the 9-variant scan family.

Outputs: qr_selection_bias.json
"""
import pandas as pd, numpy as np, json

HR = "research/highrisk"
OUT = "research/highrisk/levladder"
BLOCK, NBOOT, SEED = 60, 2000, 12345

daily = pd.read_csv(f"{OUT}/qr_daily.csv", index_col=0, parse_dates=True)
idx = daily.index
m_full = (np.arange(len(idx)) >= 200) & (idx >= "2020-01-01") & (idx <= "2026-10-31")
n = int(m_full.sum())

FAMILY = ["L1.5_rv50", "L1.5_rv50_dd15", "L1.5_rv50_dd20",
          "strategist_1.5_rv60",          # == L1.5_rv60, pre-registered (spec section 8)
          "L1.5_rv60_dd15", "L1.5_rv60_dd20",
          "L1.5_rv70", "L1.5_rv70_dd15", "L1.5_rv70_dd20"]
BASE = "const_1.5"


def realized(r):
    r = np.asarray(r)
    eq = np.cumprod(1.0 + r)
    yrs = len(r) / 365.0
    cagr = float(eq[-1] ** (1.0 / yrs) - 1.0) if eq[-1] > 0 else -1.0
    mdd = float((eq / np.maximum.accumulate(eq) - 1.0).min())
    sharpe = float(r.mean() / r.std(ddof=1) * np.sqrt(365.0))
    return cagr, sharpe, mdd


rng = np.random.default_rng(SEED)          # fresh -> same FULL starts as qr_01
nb = int(np.ceil(n / BLOCK))
starts = rng.integers(0, n - BLOCK + 1, size=(NBOOT, nb))
offs = np.arange(BLOCK)
bidx = (starts[:, :, None] + offs[None, None, :]).reshape(NBOOT, nb * BLOCK)[:, :n]


def boot_mdd(r):
    eq = np.cumprod(1.0 + r[bidx], axis=1)
    peak = np.maximum.accumulate(eq, axis=1)
    return (eq / peak - 1.0).min(axis=1)


def boot_cagr(r):
    eq = np.cumprod(1.0 + r[bidx], axis=1)
    yrs = n / 365.0
    return np.sign(eq[:, -1]) * np.abs(eq[:, -1]) ** (1.0 / yrs) - 1.0


base_r = daily[BASE].values[m_full]
mdd_base = boot_mdd(base_r)
cagr_base = boot_cagr(base_r)
real_base = realized(base_r)

rows = []
dmdd_mat = np.zeros((NBOOT, len(FAMILY)))
for k, a in enumerate(FAMILY):
    r = daily[a].values[m_full]
    mdd_a = boot_mdd(r)
    dmdd = mdd_a - mdd_base                     # >0 = shallower = improvement
    dmdd_mat[:, k] = dmdd
    real_a = realized(r)
    rows.append({
        "variant": a,
        "realized_mdd_pct": 100 * real_a[2],
        "realized_cagr_pct": 100 * real_a[0],
        "realized_sharpe": real_a[1],
        "dmdd_obs_pp": 100 * (real_a[2] - real_base[2]),
        "dcagr_obs_pp": 100 * (real_a[0] - real_base[0]),
        "dmdd_boot_median_pp": 100 * float(np.median(dmdd)),
        "dmdd_boot_ci95_pp": [100 * float(np.percentile(dmdd, 2.5)),
                              100 * float(np.percentile(dmdd, 97.5))],
        "p_naive": float((dmdd <= 0).mean()),
        "dcagr_boot_median_pp": 100 * float(np.median(boot_cagr(r) - cagr_base)),
    })

obs = np.array([r_["dmdd_obs_pp"] / 100 for r_ in rows])
# Romano-Wolf single-step max-stat (recentered at observed -> least-favourable null)
Z = (dmdd_mat - obs[None, :]).max(axis=1)
e_max_null = float(Z.mean())
for k, r_ in enumerate(rows):
    r_["p_bonferroni_9"] = float(min(1.0, 9 * r_["p_naive"]))
    r_["p_romanowolf_adj"] = float((Z >= obs[k]).mean())
# Holm step-down on naive p
order = np.argsort([r_["p_naive"] for r_ in rows])
holm = np.zeros(len(rows))
running = 0.0
for rank, k in enumerate(order):
    running = max(running, min(1.0, (len(rows) - rank) * rows[k]["p_naive"]))
    holm[k] = running
for k, r_ in enumerate(rows):
    r_["p_holm_9"] = float(holm[k])
    r_["pre_registered"] = r_["variant"] == "strategist_1.5_rv60"

best = int(np.argmax(obs))
out = {
    "design": {"window": "FULL_2020H2_2026", "n_days": n, "block_len": BLOCK,
               "n_boot": NBOOT, "seed": SEED, "base": BASE, "family_size": len(FAMILY)},
    "question": "does ANY conditional rule beat constant 1.5x on MDD after correcting "
                "for the 9-variant post-hoc scan?",
    "E_max_improvement_pp_under_null": 100 * e_max_null,
    "best_variant": rows[best]["variant"],
    "best_variant_dmdd_obs_pp": rows[best]["dmdd_obs_pp"],
    "best_variant_p_romanowolf": rows[best]["p_romanowolf_adj"],
    "best_variant_p_bonferroni": rows[best]["p_bonferroni_9"],
    "p_max_stat_le_0_uncentred": float((dmdd_mat.max(axis=1) <= 0).mean()),
    "pre_registered_arm": {
        "variant": "strategist_1.5_rv60",
        "spec": "STRATEGY_SPEC_v1.md section 8, frozen 2026-11-02, before ladder results",
        "verdict_basis": "uncorrected paired p vs const_1.5 from qr_01 (singleton test): "
                         "FULL dMDD +4.69pp p=0.0770; OOS dMDD +2.63pp p=0.1040",
    },
    "variants": rows,
}
with open(f"{OUT}/qr_selection_bias.json", "w") as fh:
    json.dump(out, fh, indent=2)

print(f"E[max improvement under null] = {100*e_max_null:+.2f}pp")
print(f"best: {rows[best]['variant']} obs {rows[best]['dmdd_obs_pp']:+.2f}pp "
      f"naive p={rows[best]['p_naive']:.4f} bonf={rows[best]['p_bonferroni_9']:.4f} "
      f"RW-adj={rows[best]['p_romanowolf_adj']:.4f}")
print(f"{'variant':18s} {'realMDD':>8s} {'dmddObs':>8s} {'dmddMed':>8s} {'p_naive':>8s} "
      f"{'p_bonf':>7s} {'p_holm':>7s} {'p_RW':>7s} {'dcagrMed':>9s}")
for r_ in sorted(rows, key=lambda x: -x["dmdd_obs_pp"]):
    flag = " *PRE-REG*" if r_["pre_registered"] else ""
    print(f"{r_['variant']:18s} {r_['realized_mdd_pct']:8.2f} {r_['dmdd_obs_pp']:+8.2f} "
          f"{r_['dmdd_boot_median_pp']:+8.2f} {r_['p_naive']:8.4f} {r_['p_bonferroni_9']:7.4f} "
          f"{r_['p_holm_9']:7.4f} {r_['p_romanowolf_adj']:7.4f} {r_['dcagr_boot_median_pp']:+9.2f}{flag}")
