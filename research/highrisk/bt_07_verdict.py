"""bt_07: CONSOLIDATED VERDICT — single JSON the risk-manager gates on.

Reads only bt_* artifacts (single source of truth = prior run outputs).
Applies the frozen ex-ante selection rule, states the shipped config,
and enumerates every risk flag surfaced by the battery.
"""
import pandas as pd, numpy as np, json
OUT = "research/highrisk"

parity = json.load(open(f"{OUT}/bt_parity.json"))
hr = pd.read_csv(f"{OUT}/bt_horserace.csv")
boot = json.load(open(f"{OUT}/bt_bootstrap.json"))
se = json.load(open(f"{OUT}/bt_stamp_exact.json"))
diag = json.load(open(f"{OUT}/bt_stamp_diagnose.json"))
ep = json.load(open(f"{OUT}/bt_episode2021.json"))
sens = json.load(open(f"{OUT}/bt_sensitivity.json"))
integ = json.load(open(f"{OUT}/bt_integrity.json"))

def hrow(arm, window):
    r = hr[(hr["arm"] == arm) & (hr["window"] == window)].iloc[0]
    return {k: (round(float(r[k]), 4) if k not in ("arm", "window") else r[k])
            for k in ["cagr", "sharpe", "ann_vol", "mdd", "total_x", "round_trips_per_yr",
                      "cost_drag_ann_pct", "funding_drag_ann_pct", "pct_gate_on_blocked"]}

ARMS = ["A0_baseline", "A1_VB", "A2_TS30", "A3_VB_TS"]

# ---------- frozen selection rule ----------
A0 = hrow("A0_baseline", "OOS_2022_2026")
sel = {"rule": ("A_i ships iff (i) bootstrap MDD median improves >=5pp vs A0 AND "
                "(ii) OOS CAGR >=15% AND (iii) OOS Sharpe >= A0 Sharpe - 0.10. "
                "Order: A1 -> A2 -> A3 -> A0."),
       "window_note": ("Rule text qualifies OOS for (ii)/(iii) only; criterion (i) evaluated on "
                       "FULL_2020H2_2026 (the only window containing the tail episodes the overlay "
                       "insures against; OOS contains no gate-on vol crisis). OOS-bootstrap values "
                       "reported alongside for the risk-manager."),
       "criteria": {}}
verdict_arm = None
for a in ["A1_VB", "A2_TS30", "A3_VB_TS"]:
    r = hrow(a, "OOS_2022_2026")
    imp_full = boot["mdd_median_improvement_pp_vs_A0"]["FULL_2020H2_2026"][a]
    imp_oos = boot["mdd_median_improvement_pp_vs_A0"]["OOS_2022_2026"][a]
    c1 = imp_full >= 5.0
    c2 = r["cagr"] >= 0.15
    c3 = r["sharpe"] >= A0["sharpe"] - 0.10
    passes = c1 and c2 and c3
    sel["criteria"][a] = {
        "i_mdd_median_improvement_FULL_pp": imp_full, "i_pass": bool(c1),
        "i_mdd_median_improvement_OOS_pp_COUNTEREVIDENCE": imp_oos,
        "ii_oos_cagr": r["cagr"], "ii_pass": bool(c2),
        "iii_oos_sharpe": r["sharpe"], "iii_threshold": round(A0["sharpe"] - 0.10, 4),
        "iii_pass": bool(c3), "PASSES": bool(passes),
    }
    if passes and verdict_arm is None:
        verdict_arm = a
sel["verdict"] = verdict_arm if verdict_arm else "A0_baseline"
sel["strict_oos_reading"] = ("If criterion (i) were instead required on the OOS bootstrap: "
                             "A1 -0.45pp, A2 0.00pp, A3 -0.45pp -> ALL FAIL -> ship A0 unchanged. "
                             "Flagged explicitly; risk-manager owns the final call.")

v = {
 "stage": "backtesting-engineer -> risk-manager",
 "date": "2026-11-02",
 "a_parity": {
    "verdict": parity["PARITY_VERDICT"],
    "detail": parity["verdict_note"],
    "full_dcagr_bp": parity["L3_windows"][0]["dcagr_bp"],
    "oos_dcagr_bp": parity["L3_windows"][1]["dcagr_bp"],
    "raw_data_rebuild": "4h->daily close and funding fund_sum rebuilt from raw files; "
                        "max close diff 0.0; 5m cross-check 0.0; gate states identical",
 },
 "b_horse_race": {a: {"FULL_2020H2_2026": hrow(a, "FULL_2020H2_2026"),
                      "OOS_2022_2026": hrow(a, "OOS_2022_2026"),
                      "OOS_2022": hrow(a, "OOS_2022"),
                      "OOS_2023": hrow(a, "OOS_2023"),
                      "OOS_2024_2026": hrow(a, "OOS_2024_2026")} for a in ARMS},
 "c_selection_rule": sel,
 "d_stamp_exact_shipped": {
    "config": "A1_VB (TG1x-hyst2 x VB(10,100,5)), 00:05 UTC taker, deadband +/-5%, isolated 1x",
    "FULL": se["windows"]["A1_VB_db5"]["FULL_2020H2_2026"],
    "OOS": se["windows"]["A1_VB_db5"]["OOS_2022_2026"],
    "A0_reference": {"FULL": se["windows"]["A0_baseline_db5"]["FULL_2020H2_2026"],
                     "OOS": se["windows"]["A0_baseline_db5"]["OOS_2022_2026"]},
    "boundary_check": se["boundary_check"],
    "boundary_diagnosis": {
        "flag": "A1 FULL stamp-vs-parity = -46.9bp/yr (>10bp threshold) -> DIAGNOSED, not a boundary bug",
        "decomposition_bp_per_yr": diag["deltas_bp_per_yr"],
        "root_cause": ("Single 5-min execution-timing event: breaker exit 00:05 UTC 2021-05-13 "
                       "filled 47,095.47 vs decision close 49,595.76 (-504bp, -1,675 USDT on 0.67 BTC) "
                       "during the verified May-2021 crash cascade (00:00 bar: $1.14B quote volume, "
                       "low 45,596; corroborated by mark-price and 4h series). All other fills net "
                       "~+240 USDT favorable. Funding-stamp conventions +18bp/yr; deadband +37bp/yr."),
        "interpretation": ("QR-parity 'fill at decision close' is optimistic on crash-day overlay exits; "
                           "stamp-exact is the honest number: shipped FULL MDD -42.5% (vs -38.9% parity), "
                           "FULL CAGR 33.8%, OOS CAGR 20.5%, OOS Sharpe 0.723."),
    },
    "deadband_check": {**se["deadband_check"]["A1_VB"],
                       "verdict": ("PASS on fee channel: |748.11-732.49| USDT over 6.29y ~= 2.5bp/yr-start "
                                   "< 5bp/yr. CAGR delta +36.6bp/yr is fill-price noise on 379 avoided dust "
                                   "trades + funding-drift exposure, not cost drag.")},
 },
 "e_bootstrap": {
    "design": boot["windows"]["OOS_2022_2026"] | {"per_arm": None, "paired_vs_A0": None},
    "FULL_per_arm": boot["windows"]["FULL_2020H2_2026"]["per_arm"],
    "FULL_paired": boot["windows"]["FULL_2020H2_2026"]["paired_vs_A0"],
    "OOS_per_arm": boot["windows"]["OOS_2022_2026"]["per_arm"],
    "OOS_paired": boot["windows"]["OOS_2022_2026"]["paired_vs_A0"],
 },
 "f_episode2021": {a: ep["arms"][a] for a in ARMS} | {"reference": ep["reference_A0_gate_exit"]},
 "g_sensitivity": {
    "vb_surface": sens["vb_surface_flatness"],
    "vb_surface_warning": ("P&L surface NOT flat: FULL MDD spans -34.5% (X90k10) to -56.5% (X>=110); "
                           "X>=110 misses the 2021 crash entirely; k=10 dominates k=5 in-sample AND OOS "
                           "(OOS CAGR 22.7% vs 20.4%, MDD -33.5% vs -34.8%). Chosen (100,5) is defensible "
                           "a priori but the benefit concentrates in X=90-100 with k>=5 -> amplifies "
                           "selection-bias flag #4. Report-only; not re-selected."),
    "ts_surface": sens["ts_tau25_cliff"],
    "ts_surface_warning": ("tau surface non-monotone (tau20 38.1% / tau25 33.9% / tau30 37.0% / tau35 32.8% "
                           "FULL CAGR) = documented knife-edge reproduced; tau25 lockout 2021-01-27@30,381 "
                           "-> 2021-08-09 reproduced exactly. Validates TS as fallback-only."),
 },
 "h_integrity": {
    "worst_held_days": integ["worst_held_days"],
    "trade_stats": integ["trade_stats_qr_parity_FULL"],
    "blocked_days": integ["blocked_reconciliation"],
    "funding_per_year": integ["funding_per_year_stamp_exact"],
    "deflated_sharpe": integ["deflated_sharpe"],
 },
 "risk_flags": [
    "1. OVERLAY EFFICACY IS IN-SAMPLE: VB's MDD benefit derives from the 2021 episode (in-sample for "
    "threshold choice, ledger flag #4). OOS 2022-26 VB is net cost: CAGR -1.3pp/yr, Sharpe -0.03, "
    "MDD -1.3pp worse; paired OOS bootstrap p(dCAGR<=0)=0.96, p(dMDD<=0)=0.81.",
    "2. FULL-sample paired bootstrap: dMDD median +6.0pp but p(dMDD<=0)=0.283 (not significant); "
    "dCAGR p=0.46. The overlay's improvement is economically large, statistically unresolved.",
    "3. SHIPPED MDD -42.5% (stamp-exact FULL) exceeds strategist projection -40%; sits inside user "
    "tolerance 40-50% but with reduced margin. One verified crash-cascade 5-min fill (2021-05-13, "
    "-504bp vs decision close) accounts for ~3.6pp of trough depth vs parity accounting.",
    "4. SELECTION-RULE WINDOW AMBIGUITY: verdict hinges on reading criterion (i) on FULL (A1 ships) "
    "vs OOS (A0 ships). My reading: FULL (rule qualifies OOS explicitly for (ii)/(iii) only; bootstrap "
    "defined per arm x window in spec 13.4; tail insurance is only measurable where tails exist).",
    "5. OOS point estimates vs target: shipped OOS CAGR 20.5% (>=15% target met), but 2024-26 sub-window "
    "CAGR 12.4% < 15%; OOS Sharpe 0.723. Honest forward ~15-20%/yr is achievable only if 2023-type "
    "trend years recur; 2022-type years earn 0 (flat).",
    "6. Parameter surface is not flat in P&L terms (k=10 > k=5 everywhere; X>=110 useless) - the "
    "shipped (100,5) is mid-pack, not optimal; do not re-optimize (frozen), but size for model risk.",
    "7. Statistical fragility inherited from QR: gate edge vs no-gate p~0.14-0.25; DSR(A0)=0.883, "
    "DSR(A1)=0.870 (N=30 trials) - below the 0.95 bar; evidence base ~2 bears.",
    "8. Funding regime: 2021 in-market funding bleed -41.8% of start-of-year equity (A0) / -24.8% (A1); "
    "2026 only -1.25%. A 2021-repeat compresses in-market CAGR toward zero; monitoring KPI per spec 14.",
    "9. A1 vs A0 cost of insurance OOS: -1.3pp/yr CAGR + 2.6% extra blocked gate-on days; "
    "premium is dead cost in no-crisis regimes by construction.",
    "10. Worst held day A1 = -12.68% (2021-05-12, breaker reacts next execution only); unconditional "
    "BTC worst day -40% (2020-03-12, flat) is the honest tail for any 1x long; no daily-close overlay "
    "reacts faster than the print.",
 ],
 "artifacts": {
    "code": ["bt_00_parity.py", "bt_01_horserace.py", "bt_02_bootstrap.py", "bt_03_stamp_exact.py",
             "bt_03b_diagnose.py", "bt_04_episode2021.py", "bt_05_sensitivity.py", "bt_06_integrity.py",
             "bt_07_verdict.py", "bt_common.py"],
    "data": ["bt_parity.json", "bt_horserace.csv", "bt_daily.csv", "bt_trace_check.json",
             "bt_bootstrap.json", "bt_stamp_exact.json", "bt_stamp_diagnose.json", "bt_stamp_daily.csv",
             "bt_trade_log.csv", "bt_episode2021.json", "bt_episode2021_daily.csv",
             "bt_sensitivity_vb.csv", "bt_sensitivity_ts.csv", "bt_sensitivity.json",
             "bt_integrity.json", "bt_verdict.json"],
 },
}
# drop the None placeholder keys
v["e_bootstrap"]["design"] = {k: v2 for k, v2 in v["e_bootstrap"]["design"].items() if v2 is not None}
with open(f"{OUT}/bt_verdict.json", "w") as fh:
    json.dump(v, fh, indent=2, default=str)
print("verdict:", sel["verdict"])
print(json.dumps(sel["criteria"], indent=2))
print("wrote bt_verdict.json")
