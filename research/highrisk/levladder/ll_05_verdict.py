"""ll_05: TASK 5 — verdict ladder + handoff report for quant-researcher.

Reading rules (pre-specified for this analyst step):
  PASS-TO-QR  = geometry survivable on the gate's actual path, with or without a
                simple causal condition (no liquidation, no dust close).
  KILLED      = liquidation on the actual path that no simple causal rule dodges.
  Economic-ruin flag: MDD <= -80% or CAGR collapse from deleverage churn even
  without an exchange liquidation (5x conditional lives here).
  Mandate flag: FULL MDD beyond the user's 40-50% tolerance band.

Outputs: verdict.json, LEVERAGE_LADDER_REPORT.md
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "research/highrisk/levladder")
from ll_common import OUT, load_daily

def md_table(df: pd.DataFrame) -> str:
    """Minimal markdown table (no tabulate dependency)."""
    df = df.copy()
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


daily = load_daily()
arms = pd.read_csv(f"{OUT}/arms_summary.csv")
byep = pd.read_csv(f"{OUT}/ladder_by_episode.csv")
exc = pd.read_csv(f"{OUT}/episodes_excursions.csv")
drag = pd.read_csv(f"{OUT}/drag_scaling.csv")

A = arms.set_index("arm")

# ------------------------------------------------------- dodge forensics (rv10)
def rv10_around(a, b):
    s = daily.loc[a:b, ["close", "rv10"]].copy()
    s["rv10"] = s["rv10"].round(3)
    return s

forensics = {
    "kill_5x_const_ep1": {
        "kill_time": "2021-01-11 16:35 (mark 30,473.55 < LP 30,506; gate exit was 00:05 2021-01-12)",
        "rv10_path": rv10_around("2020-12-28", "2021-01-12").to_dict("index"),
        "reading": "rv10 was >=0.60 for the whole week before the kill (0.63-0.95 from "
                   "2021-01-02 onward). An rv10<=60% rule is at 1x from 00:05 01-03, "
                   "8.5 days before the kill bar -> dodges the 5x liquidation (confirmed: "
                   "L5.0_rv60 dead=False), but the toggle whipsaw still costs -98.7% MDD.",
    },
    "kill_10x_rv60_ep1": {
        "kill_time": "2020-09-03 23:25 (rv60 rule had dodged the 2020-08-02 flash dump)",
        "rv10_path": rv10_around("2020-08-28", "2020-09-04").to_dict("index"),
        "reading": "rv10 0.32-0.45 all week -> rule is AT 10x into the 2020-09-03 -11% "
                   "gap day; 10x LP = 9.64% -> dies. Calm-to-crash gap days are "
                   "invisible to vol state. 10x is not saveable by rv10 gates.",
    },
    "kill_10x_const_ep12": {
        "kill_time": "2024-04-13 20:05 (entry rv10 0.461, leveraged under rv60)",
        "rv10_path": rv10_around("2024-03-31", "2024-04-14").to_dict("index"),
        "reading": "rv10 oscillated 0.51-0.62 around the 0.60 threshold: deleveraged "
                   "00:05 04-03 (rv10 0.618), RE-leveraged 00:05 04-05 (rv10 0.527), out "
                   "00:05 04-10 (0.604), back IN 00:05 04-11 (0.599) -> at 10x on the "
                   "kill bar. Threshold knife-edge: survival is threshold luck, not skill.",
    },
    "kill_10x_const_ep11": {
        "kill_time": "2024-01-12 22:20 (entry rv10 0.353)",
        "rv10_path": rv10_around("2024-01-08", "2024-01-13").to_dict("index"),
        "reading": "rv10 0.59-0.63 all week, straddling 0.60: out 00:05 01-09 (0.606), "
                   "back IN 00:05 01-12 (0.590) -> killed the same night. Knife-edge again.",
    },
    "kill_10x_const_ep17": {
        "kill_time": "2025-10-10 21:10 (entry rv10 0.461)",
        "rv10_path": rv10_around("2025-10-06", "2025-10-11").to_dict("index"),
        "reading": "rv10 0.24-0.35 the whole week -> every vol rule is fully leveraged "
                   "into the 2025-10-10 cascade. Pure calm-to-crash gap; undodgeable.",
    },
}

# ------------------------------------------------------- per-L verdict assembly
def arm_row(name):
    return A.loc[name] if name in A.index else None

verdicts = []
for L in (1.5, 2.0, 3.0, 5.0, 10.0):
    c = arm_row(f"const_{L}")
    kills = byep[(byep["L"] == L) & (byep["liquidated"])]
    kill_eps = [int(e) for e in kills["ep"]]
    # best conditional variant at this L by MDD (rv-only and rv+dd)
    cond = arms[(arms["L_max"] == L) & (arms["kind"] == "cond")]
    best = cond.loc[cond["FULL_mdd_pct"].idxmax()] if len(cond) else None
    strat = arm_row("strategist_1.5_rv60") if L == 1.5 else None
    dead_any_cond = bool(cond["dead"].any()) if len(cond) else None
    v = {
        "L": L,
        "lp_dist_pct": float(drag[drag["L"] == L]["lp_dist_pct"].iloc[0]),
        "const_dead": bool(c["dead"]),
        "const_kill_episodes": kill_eps,
        "const_FULL_cagr_pct": float(c["FULL_cagr_pct"]),
        "const_FULL_mdd_pct": float(c["FULL_mdd_pct"]),
        "const_FULL_sharpe": float(c["FULL_sharpe"]),
        "const_OOS_cagr_pct": float(c["OOS_cagr_pct"]) if np.isfinite(c["OOS_cagr_pct"]) else None,
        "const_OOS_mdd_pct": float(c["OOS_mdd_pct"]) if np.isfinite(c["OOS_mdd_pct"]) else None,
        "const_n_trades": int(c["n_trades"]),
        "naive_Lx_mdd_pct": round(L * -42.5, 1),
        "any_conditional_dies": dead_any_cond,
        "best_cond_arm": best["arm"] if best is not None else None,
        "best_cond_mdd_pct": float(best["FULL_mdd_pct"]) if best is not None else None,
        "best_cond_cagr_pct": float(best["FULL_cagr_pct"]) if best is not None else None,
        "strategist_rv60_mdd_pct": float(strat["FULL_mdd_pct"]) if strat is not None else None,
        "strategist_rv60_cagr_pct": float(strat["FULL_cagr_pct"]) if strat is not None else None,
    }
    # verdict logic
    if L in (1.5, 2.0, 3.0):
        v["verdict"] = "PASS-TO-QR"
        v["basis"] = "no liquidation or dust close on any of the 18 episodes, unconditional"
    elif L == 5.0:
        v["verdict"] = "PASS-TO-QR (conditional only) + ECONOMIC-RUIN FLAG"
        v["basis"] = ("liquidated unconditionally in ep1 (2021-01-11, pyramided entry, "
                      "7.5h before gate exit); rv10<=50/60% condition dodges the liquidation "
                      "but the book still grinds to -98% MDD with negative CAGR")
    else:
        v["verdict"] = "KILLED"
        v["basis"] = ("liquidated in 11/18 episodes unconditionally (first: ep1, 2020-08-02 "
                      "flash dump, day 14); rv10<=50/60% conditions still die in ep1 "
                      "(2020-09-03): calm-to-crash gap days are invisible to vol state")
    # mandate flag (user tolerance -40..-50%)
    mdd_pool = [v["const_FULL_mdd_pct"], v["best_cond_mdd_pct"] or -100]
    v["mandate_breach"] = bool(min(mdd_pool) < -50.0)
    v["mandate_note"] = (
        "breaches -50% ceiling at every variant" if min(mdd_pool) < -50 else
        "inside band at best variant")
    verdicts.append(v)

# tightest survivable ladders
surv_all_const = [L for L in (1.5, 2.0, 3.0, 5.0, 10.0)
                  if not A.loc[f"const_{L}", "dead"]]
cond_surv = arms[(arms["kind"] == "cond") & (~arms["dead"])]
surv_all_cond = sorted(cond_surv["L_max"].unique())
verdict_meta = {
    "tightest_L_survives_all_episodes_const": max(surv_all_const),
    "tightest_L_survives_all_episodes_conditional": max(surv_all_cond),
    "tightest_L_survives_all_but_one_const": 5.0,
    "note_all_but_one": ("5x const dies only in ep1 (2021-01-11); 10x dies in 11/18 "
                         "(not all-but-one). 'Survives' = no exchange liquidation; 3x "
                         "const ends with -92.3% MDD = economic near-ruin."),
    "n_episodes": 18,
    "episodes_killing_each_L": {str(L): [int(e) for e in byep[(byep["L"] == L) &
                                        (byep["liquidated"])]["ep"]]
                                for L in (1.5, 2.0, 3.0, 5.0, 10.0)},
}

with open(f"{OUT}/verdict.json", "w") as fh:
    json.dump({"verdicts": verdicts, "ladder_meta": verdict_meta,
               "forensics": {k: {kk: vv for kk, vv in f.items() if kk != "rv10_path"}
                             for k, f in forensics.items()}}, fh, indent=2, default=str)

# ------------------------------------------------------- report
vd = pd.DataFrame(verdicts)
kill_tbl = byep[byep["liquidated"]][["ep", "entry_day", "L", "kill_time",
                                     "lp_dist_pct_at_entry", "tier_at_entry"]]
rep = []
rep.append("# Leverage ladder on the shipped A1 book — crypto-defi-analyst step\n")
rep.append("Date 2026-11-02. Engine: `ll_common.Book` re-validated against the shipped "
           "backtest (`validation_1x.json`, all pass): 1x arm reproduces 18/18 episodes, "
           "40/40 trades, funding/yr to the cent (2021 −24.76%, 2024 −14.75%), FULL MDD "
           "−42.50% and OOS MDD −35.31% exact, FULL CAGR 33.67% vs shipped 33.78% "
           "(11bp/yr: mark-vs-trade stamp pricing on re-simulated deadband trims). All "
           "numbers from local Binance files; liquidation checked on 5m mark lows with "
           "real funding stamps, tier-aware MMR, shipped ±5% deadband mechanics.\n")
rep.append("## Verdict ladder (for quant-researcher)\n")
rep.append(md_table(vd[["L", "verdict", "const_kill_episodes", "const_FULL_cagr_pct",
                        "const_FULL_mdd_pct", "naive_Lx_mdd_pct", "best_cond_arm",
                        "best_cond_mdd_pct", "mandate_breach"]]))
rep.append("\n## Key structural finding: two different kill mechanisms\n")
rep.append(
    "1. **Entry-anchored geometry (static screen) looks deceptively safe.** Worst adverse "
    "mark excursion vs episode-entry fill across all 18 episodes is **18.83%** (ep12, "
    "2024-05-01). Against entry-time LP distances, even 5x (19.68%) breaches **zero** "
    "episodes; only 10x (9.64%) breaches, in 6 episodes. The gate+breaker exits crashes "
    "within days, so the path is far gentler than mom10x's constant-leverage month-holds "
    "(3x died 3/76, 5x 13/76 there).\n"
    "2. **The dynamic book pyramids.** Holding notional = L×equity with the shipped ±5% "
    "deadband forces ADDS on the way up (ratio falls as equity grows), blending EP upward. "
    "After the 2020H2 bull, ep1's 5x book had re-anchored near 40k and died in the "
    "Jan-11-2021 correction at mark 30,473.55 vs LP 30,506 — **7.5 hours before the "
    "breaker's own exit** (00:05 01-12). 10x died the same way in the 2020-08-02 flash "
    "dump (day 14 of ep1). Static excursion screens miss this entirely; any leverage "
    "backtest must model the deadband adds, not just episode-entry LP distance.\n")
rep.append("## Episode kill map (standalone episode sims)\n")
rep.append(md_table(kill_tbl))
rep.append("\n\nMin within-episode equity ratio per L (1.0 = never underwater; "
           "<0.25 = economic near-ruin):\n")
piv = byep.pivot_table(index=["ep", "entry_day"], columns="L", values="min_equity_ratio")
rep.append(md_table(piv.round(3).reset_index()))
rep.append("\n## Conditional rules (rv10<=X at decision close, optional dd-from-episode-peak)\n")
cond_out = arms[arms["kind"] == "cond"][["arm", "dead", "kill_ep", "FULL_cagr_pct",
                                         "FULL_mdd_pct", "FULL_sharpe", "OOS_cagr_pct",
                                         "OOS_mdd_pct", "n_trades", "fees_total_usdt"]]
rep.append(md_table(cond_out))
rep.append(f"\n\nGate-on days with rv10≤60%: **71.2%** (≤50%: 57.4%, ≤70%: 81.3%). "
           "Kill forensics by type (verified rv10 paths in `verdict.json`): "
           "(i) **pyramid-then-correction** — the 5x ep1 kill (2021-01-11): rv10 had been "
           ">60% for a week, so an rv10≤60% rule is flat-to-1x 8.5 days before the kill "
           "bar and dodges the liquidation (but the toggle whipsaw still costs −98.7% MDD "
           "at 5x); (ii) **calm-to-crash gap days** — 2020-09-03 (rv10 0.32–0.45 all "
           "week), 2025-10-10 (0.24–0.35): invisible to any vol-state rule, undodgeable; "
           "(iii) **threshold knife-edge** — eps 11/12 at 10x: rv10 straddles 0.60 "
           "(0.51–0.63), the rule toggles out and back in days before the kill bar "
           "(re-leveraged 00:05 04-11 at rv10 0.599, killed 04-13 20:05) — survival is "
           "threshold luck, not skill. dd-from-peak overlays (15%/20%) consistently "
           "*reduce* CAGR via whipsaw without improving MDD — dead end.\n")
rep.append("## Drag scaling (per unit of margin equity)\n")
rep.append(md_table(drag[["L", "lp_dist_pct", "fund_inmarket_2021_pct", "fund_inmarket_2024_pct",
                          "fund_inmarket_2026_pct", "fund_inmarket_OOS_pct", "taker_per_roundtrip_pct",
                          "fee_drag_ann_pct_sim", "breakeven_g_inmarket_FULL_pct",
                          "gross_g_FULL_pct", "net_uplift_per_unit_FULL_pct"]]))
rep.append(f"\n\nIn-market funding at 1x per notional-year: 2021 **35.0%**, 2024 14.1%, "
           "2026 5.8%, OOS-avg 9.3% — at L it is L×. Break-even gross held return "
           "FULL ≈ 15.2%/yr vs realized 82.8%/yr: per-unit economics justify leverage "
           "in-sample, but realized compounding caps at 2x (3x CAGR 44.9% < 2x 51.6%) "
           "because fee churn (3x: 393 trades, 21.8%/yr fee drag) and deleverage-releverage "
           "convexity eat the theoretical uplift.\n")
rep.append("## Mandate check (user MDD tolerance 40–50%)\n")
rep.append(
    "- 1x shipped: −42.5% realized (inside), bootstrap median −47.4%, worst −74.6%.\n"
    "- **1.5x**: const −59.5%, strategist rv60 −54.7%, best variant (rv50) −49.8% — only "
    "inside the band by post-hoc variant picking (9-variant scan = selection bias).\n"
    "- **2x**: −74.9% const, −62.2% best conditional. Far outside.\n"
    "- **3x**: −92.3% const. Near-ruin without liquidation.\n"
    "- Bootstrap envelope at 1x already reaches −74.6%; any L>1 puts total ruin inside "
    "the 95% envelope. The mandate as stated (40–50%) admits **no leverage >1x** "
    "without either raising tolerance or accepting a post-hoc-picked condition.\n")
rep.append("## Handoff to quant-researcher\n")
rep.append(
    "Arms worth a real backtest (in priority order): (1) **constant 1.5x** — cleanest, "
    "survives everything, CAGR 44.8% vs 33.7%, MDD −59.5% is the blocker; "
    "(2) **strategist's spec-§8 arm** (1.5x iff rv10≤60%) — CAGR 38.4%, MDD −54.7%; "
    "(3) **constant 2x** — geometry survives, CAGR 51.6%, MDD −74.9% needs an explicit "
    "tolerance raise. Do NOT backtest 5x/10x as constants (liquidated on the actual "
    "path). Backtest engine MUST implement the deadband adds (EP blending) — entry-"
    "anchored LP checks are non-conservative by up to 3x on this path (5x static-safe, "
    "5x dynamic-dead). Bootstrap any candidate: 1x worst-resample −74.6% scales ~L×.\n")
rep.append("## Files\n"
           "- `episodes_excursions.csv` (task 1), `ladder_static.csv` / `ladder_dynamic.csv` "
           "/ `ladder_by_episode.csv` (task 2), `conditional_rules.csv` / "
           "`conditional_stats.json` (task 3), `drag_scaling.csv` / `drag_regimes.json` "
           "(task 4), `verdict.json` (task 5), `book_*.json` per-arm equity + episode "
           "detail, `ll_common.py` engine, `validation_1x.json` engine parity.\n")

with open(f"{OUT}/LEVERAGE_LADDER_REPORT.md", "w") as fh:
    fh.write("\n".join(rep))

print(vd[["L", "verdict", "const_kill_episodes", "const_FULL_mdd_pct",
          "best_cond_arm", "best_cond_mdd_pct", "mandate_breach"]].to_string(index=False))
print(json.dumps(verdict_meta, indent=2, default=str))
for k, f in forensics.items():
    print(f"\n== {k}: {f['kill_time']}")
    for d, v in f.get("rv10_path", {}).items():
        print("  ", d.date(), v)
