"""qr_03: assemble the quant-researcher verdict for the leverage-ladder request.

Inputs: qr_bootstrap.json (qr_01), qr_selection_bias.json (qr_02), qr_daily.csv,
analyst's arms_summary.csv. Adds the best post-hoc variant's boot MDD envelope
(same rng design -> identical FULL draws) for the mandate table.

Outputs: qr_verdict.json, qr_mandate_table.csv
"""
import pandas as pd, numpy as np, json

HR = "research/highrisk"
OUT = "research/highrisk/levladder"
BLOCK, NBOOT, SEED = 60, 2000, 12345
TOL_LO, TOL_HI = 0.40, 0.50          # user mandate band

boot = json.load(open(f"{OUT}/qr_bootstrap.json"))
sel = json.load(open(f"{OUT}/qr_selection_bias.json"))
daily = pd.read_csv(f"{OUT}/qr_daily.csv", index_col=0, parse_dates=True)
idx = daily.index

# ---- best post-hoc variant boot MDD envelope (identical FULL draws as qr_01/02)
m_full = (np.arange(len(idx)) >= 200) & (idx >= "2020-01-01") & (idx <= "2026-10-31")
n = int(m_full.sum())
rng = np.random.default_rng(SEED)
nb = int(np.ceil(n / BLOCK))
starts = rng.integers(0, n - BLOCK + 1, size=(NBOOT, nb))
bidx = (starts[:, :, None] + np.arange(BLOCK)[None, None, :]).reshape(NBOOT, nb * BLOCK)[:, :n]


def boot_mdd(r):
    eq = np.cumprod(1.0 + r[bidx], axis=1)
    return (eq / np.maximum.accumulate(eq, axis=1) - 1.0).min(axis=1)


best_var = sel["best_variant"]
mdd_best = boot_mdd(daily[best_var].values[m_full])
best_env = {"mdd_median": float(np.median(mdd_best)),
            "mdd_ci95": [float(np.percentile(mdd_best, 2.5)), float(np.percentile(mdd_best, 97.5))],
            "p_mdd_worse_than_50pct": float((mdd_best <= -0.50).mean())}

# ---- mandate-fit table
ARMS = ["const_1.0", "const_1.5", "strategist_1.5_rv60", "const_2.0", "const_3.0"]
rows = []
full = boot["windows"]["FULL_2020H2_2026"]
for a in ARMS:
    rz = full["per_arm_realized"][a]
    bt = full["per_arm_boot"][a]
    fits_realized = abs(rz["mdd"]) <= TOL_HI + 1e-12
    min_tol_realized = float(np.ceil(100 * abs(rz["mdd"])))
    min_tol_bootmed = float(np.ceil(100 * abs(bt["mdd"]["median"])))
    rows.append({
        "arm": a,
        "realized_cagr_pct": round(100 * rz["cagr"], 2),
        "realized_mdd_pct": round(100 * rz["mdd"], 2),
        "realized_sharpe": round(rz["sharpe"], 3),
        "realized_calmar": round(rz["calmar"], 3),
        "boot_mdd_median_pct": round(100 * bt["mdd"]["median"], 2),
        "boot_mdd_ci95_worst_pct": round(100 * bt["mdd"]["ci95"][0], 2),
        "p_mdd_worse_than_50pct": round(bt["p_mdd_worse_than_50pct"], 3),
        "fits_mandate_40_50_realized": bool(fits_realized),
        "min_mdd_tolerance_pct_realized": min_tol_realized,
        "min_mdd_tolerance_pct_boot_median": min_tol_bootmed,
    })
rows.append({
    "arm": f"{best_var} (post-hoc best of 9)",
    "realized_cagr_pct": round([v for v in sel["variants"] if v["variant"] == best_var][0]["realized_cagr_pct"], 2),
    "realized_mdd_pct": round([v for v in sel["variants"] if v["variant"] == best_var][0]["realized_mdd_pct"], 2),
    "realized_sharpe": round([v for v in sel["variants"] if v["variant"] == best_var][0]["realized_sharpe"], 3),
    "realized_calmar": round([v for v in sel["variants"] if v["variant"] == best_var][0]["realized_cagr_pct"] /
                             abs([v for v in sel["variants"] if v["variant"] == best_var][0]["realized_mdd_pct"]), 3),
    "boot_mdd_median_pct": round(100 * best_env["mdd_median"], 2),
    "boot_mdd_ci95_worst_pct": round(100 * best_env["mdd_ci95"][0], 2),
    "p_mdd_worse_than_50pct": round(best_env["p_mdd_worse_than_50pct"], 3),
    "fits_mandate_40_50_realized": True,   # -49.77% inside by 0.23pp, via selection
    "min_mdd_tolerance_pct_realized": 50.0,
    "min_mdd_tolerance_pct_boot_median": float(np.ceil(100 * abs(best_env["mdd_median"]))),
})
mdf = pd.DataFrame(rows)
mdf.to_csv(f"{OUT}/qr_mandate_table.csv", index=False)


def pair(window, name):
    for p in boot["windows"][window]["paired"]:
        if p["pair"] == name:
            return p
    return None


verdict = {
    "stage": "quant-researcher -> algo-strategist",
    "date": "2026-11-02",
    "question": "upgrade shipped TG1x-hyst2 x VB(10,100,5) 1x book to higher leverage?",
    "harness": boot["harness_validation_vs_bt_verdict"],
    "sample_sizes": {w: boot["windows"][w]["n_days"] for w in boot["windows"]},
    "limitation": "bootstrap resamples close-to-close daily net returns; intraday (5m mark) "
                  "liquidation paths are outside its geometry. Analyst's 5m sims: no kills <=2x "
                  "on the realized path, but deep bootstrap resamples at >=2x approach LP distances "
                  "where intraday kills become plausible (2x LP ~50% adverse from a pyramided EP).",
    "a_is_the_uplift_real": {
        "const_1.5_vs_1x": {
            "dcagr_median_pp_FULL": round(100 * pair("FULL_2020H2_2026", "const_1.5 - const_1.0")["dcagr_median"], 2),
            "p_dcagr_le_0_FULL": pair("FULL_2020H2_2026", "const_1.5 - const_1.0")["p_dcagr_le_0"],
            "dcagr_median_pp_OOS": round(100 * pair("OOS_2022_2026", "const_1.5 - const_1.0")["dcagr_median"], 2),
            "p_dcagr_le_0_OOS": pair("OOS_2022_2026", "const_1.5 - const_1.0")["p_dcagr_le_0"],
            "dmdd_median_pp_FULL": round(100 * pair("FULL_2020H2_2026", "const_1.5 - const_1.0")["dmdd_median"], 2),
            "p_dmdd_le_0_FULL": pair("FULL_2020H2_2026", "const_1.5 - const_1.0")["p_dmdd_le_0"],
        },
        "const_2.0_vs_1x": {
            "dcagr_median_pp_FULL": round(100 * pair("FULL_2020H2_2026", "const_2.0 - const_1.0")["dcagr_median"], 2),
            "p_dcagr_le_0_FULL": pair("FULL_2020H2_2026", "const_2.0 - const_1.0")["p_dcagr_le_0"],
            "dmdd_median_pp_FULL": round(100 * pair("FULL_2020H2_2026", "const_2.0 - const_1.0")["dmdd_median"], 2),
            "p_dmdd_le_0_FULL": pair("FULL_2020H2_2026", "const_2.0 - const_1.0")["p_dmdd_le_0"],
        },
        "reading": "CAGR uplift is economically large but statistically UNRESOLVED "
                   "(~82% of resamples positive at 1.5x, p=0.18; ~76% at 2x, p=0.25). "
                   "MDD worsening is statistically CERTAIN: p(dMDD<=0)=1.0000 at every rung - "
                   "all 2000 paired resamples draw down deeper under leverage.",
    },
    "b_risk_adjusted_truth": {
        "realized_sharpe_FULL": {a: round(full["per_arm_realized"][a]["sharpe"], 3) for a in ARMS},
        "realized_calmar_FULL": {a: round(full["per_arm_realized"][a]["calmar"], 3) for a in ARMS},
        "dsharpe_vs_1x": {a: {"median": round(pair("FULL_2020H2_2026", f"{a} - const_1.0")["dsharpe_median"], 4),
                              "p_le_0": pair("FULL_2020H2_2026", f"{a} - const_1.0")["p_dsharpe_le_0"]}
                          for a in ARMS if a != "const_1.0"},
        "reading": "Leverage scales return AND risk symmetrically: realized Sharpe is flat "
                   "(0.917-0.918 at 1x/1.5x/2x; dSharpe median ~0, p~0.5) and DEGRADES at 3x "
                   "(0.903) as churn convexity bites. Calmar deteriorates monotonically "
                   "0.79 -> 0.75 -> 0.69 -> 0.49. Raw CAGR peaks at 2x (51.6% > 3x 44.9%) while "
                   "risk-adjusted performance peaks at 1x. Leverage buys raw CAGR only.",
    },
    "c_selection_bias": {
        "family_size": 9,
        "best_variant": best_var,
        "best_variant_dmdd_realized_pp": sel["best_variant_dmdd_obs_pp"],
        "best_variant_dmdd_boot_median_pp": [v for v in sel["variants"] if v["variant"] == best_var][0]["dmdd_boot_median_pp"],
        "p_naive": [v for v in sel["variants"] if v["variant"] == best_var][0]["p_naive"],
        "p_bonferroni": sel["best_variant_p_bonferroni"],
        "p_holm": [v for v in sel["variants"] if v["variant"] == best_var][0]["p_holm_9"],
        "p_romanowolf_maxstat": sel["best_variant_p_romanowolf"],
        "E_max_under_null_pp": sel["E_max_improvement_pp_under_null"],
        "p_at_least_one_variant_improves_uncentred": 1 - sel["p_max_stat_le_0_uncentred"],
        "pre_registered_strategist_rv60": {
            "dmdd_median_pp_FULL_vs_const15": round(100 * pair("FULL_2020H2_2026", "strategist_1.5_rv60 - const_1.5")["dmdd_median"], 2),
            "p_FULL": pair("FULL_2020H2_2026", "strategist_1.5_rv60 - const_1.5")["p_dmdd_le_0"],
            "dmdd_median_pp_OOS_vs_const15": round(100 * pair("OOS_2022_2026", "strategist_1.5_rv60 - const_1.5")["dmdd_median"], 2),
            "p_OOS": pair("OOS_2022_2026", "strategist_1.5_rv60 - const_1.5")["p_dmdd_le_0"],
            "dcagr_median_pp_FULL_vs_const15": round(100 * pair("FULL_2020H2_2026", "strategist_1.5_rv60 - const_1.5")["dcagr_median"], 2),
        },
        "reading": "Even the BEST of the 9 scanned variants fails the naive resampling test "
                   "(p=0.084) and dies under Bonferroni (0.75)/Holm (0.68). The Romano-Wolf "
                   "max-statistic says the family's best improvement exceeds what selection alone "
                   "produces (p=0.010; E[max|null]=+1.3pp vs +9.8pp realized) - so a real but "
                   "modest MDD effect exists (+6.3pp boot median, CI95 [-2.1,+15.7] crosses 0). "
                   "The pre-registered rv60 arm (bias-free): +4.7pp median, p=0.077 FULL / "
                   "0.104 OOS - NOT significant, costs -6.3pp/yr CAGR. No conditional rule "
                   "delivers a mandate-rescuing MDD after correction.",
    },
    "d_mandate_fit": rows,
    "e_recommendation": {
        "arms_to_algo_strategist": [],
        "conditional_path": {
            "if_user_raises_tolerance_to_60pct": {
                "arm": "const_1.5",
                "frozen_definition": {
                    "signal": "TG1x-hyst2 (QR-frozen, unchanged)",
                    "overlay": "VB(10,100,5) (frozen, unchanged)",
                    "margin": "isolated, dedicated sub-account",
                    "leverage_target": "1.5x equity, constant (no conditional)",
                    "deadband": "+/-5% of 1.5x target (shipped mechanic extended to L)",
                    "execution": "00:05 UTC taker, 5bp/side, full-clip",
                    "liquidation_distance_at_entry": "~66.5% adverse (tier-1 MMR)",
                },
                "expected": "FULL CAGR 44.8% (vs 33.7%), realized MDD -59.5%, boot MDD median "
                            "-65.2% CI95 worst -90.0%, P(MDD<-50%)=0.89; dCAGR +11.0pp p=0.18; "
                            "Sharpe unchanged 0.917; Calmar 0.75 (vs 0.79)",
                "requires": "risk-manager amends the 1x hard cap (risk_checks.json) AND user "
                            "raises MDD tolerance to >=60% (>=66% to cover the bootstrap median)",
            },
            "if_tolerance_55pct": "strategist_1.5_rv60 (spec section 8, pre-registered) is the "
                                  "only arm with realized MDD (-54.7%) near the band, but its "
                                  "bootstrap median -60.7% still breaches 55%; offer only with "
                                  "the statistical caveat attached",
        },
        "stay_at_1x_if": "mandate stays 40-50%. Shipped book: realized -42.5%, boot median "
                         "-49.4%, P(breach 50%)=0.48 - the current mandate already tolerates a "
                         "coin-flip breach probability at 1x",
        "killed": "3x (realized -92.3%, economic near-ruin, CAGR<2x => dominated), 5x/10x "
                  "(liquidated on realized path per analyst 5m sims)",
        "bottom_line": "1.5x improves CAGR but NO arm fits the 40-50% mandate. The uplift is "
                       "directionally likely (p=0.18) but not statistically proven; the MDD cost "
                       "is certain (p=1.0). User must raise tolerance to ~60% (1.5x constant) or "
                       "stay at 1x. There is no statistically honest path to 2x+.",
    },
    "risk_manager_handoff_flags": [
        "MDD worsening under leverage is statistically certain (p=1.0000, all 2000 resamples) - this is a deterministic scaling fact, not a risk estimate.",
        "CAGR uplift at 1.5x: 82% of resamples positive, p=0.18 - same 'economically large, statistically unresolved' signature as the VB overlay itself (bt_verdict flag 2).",
        "Bootstrap is close-to-close; intraday liquidation channel priced separately by analyst (no kills <=2x realized). At 2x, boot CI95 worst -96.4% approaches pyramided-EP LP distances; if 2x is ever reconsidered, a 5m-path bootstrap is mandatory first.",
        "Funding regime scaling: 2021-style in-market funding 35%/yr at 1x becomes 52.5%/yr at 1.5x, 70%/yr at 2x (analyst drag table, L-linear). risk_checks.json stress_A (25%/yr in-market) cut OOS CAGR 20.4%->11.1% at 1x; the same stress at 1.5x would compress it toward ~9% (linear extrapolation, not re-simulated).",
        "Even at shipped 1x, 48% of bootstrap resamples breach the -50% ceiling (book accounting; 42% on QR-parity series). The mandate band itself sits at the edge of the 1x envelope.",
        "Conditional rules add threshold knife-edge toggles (analyst forensics eps 11/12: survival was threshold luck) for a non-significant +4.7pp MDD median benefit at -6.3pp/yr CAGR cost.",
    ],
}
with open(f"{OUT}/qr_verdict.json", "w") as fh:
    json.dump(verdict, fh, indent=2)
print(mdf.to_string(index=False))
print("\nqr_verdict.json written.")
