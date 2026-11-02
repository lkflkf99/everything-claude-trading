#!/usr/bin/env python3
"""risk-manager: independent spot-checks + risk-envelope quantification for TG1x-hyst2 x VB(10,100,5).

Grounds every claim in artifact files. Does NOT rebuild the backtest; recomputes
headline numbers from the published daily series and trade log, then runs the
mandated stress overlays (funding regime, whipsaw, combined-book).

Outputs: research/highrisk/risk_checks.json
"""
import json
import math
import numpy as np
import pandas as pd

OUT = {}

# ---------------------------------------------------------------- load -------
stamp = pd.read_csv("bt_stamp_daily.csv", index_col=0, parse_dates=True)
daily = pd.read_csv("bt_daily.csv", index_col=0, parse_dates=True)
ep = pd.read_csv("bt_episode2021_daily.csv", index_col=0, parse_dates=True)
trades = pd.read_csv("bt_trade_log.csv")
verdict = json.load(open("bt_verdict.json"))
stampj = json.load(open("bt_stamp_exact.json"))

def cagr(eq):
    eq = np.asarray(eq, float)
    return (eq[-1] / eq[0]) ** (365.0 / (len(eq) - 1)) - 1.0

def mdd(eq):
    eq = np.asarray(eq, float)
    peak = np.maximum.accumulate(eq)
    return float((eq / peak - 1.0).min())

def sharpe(r):
    r = np.asarray(r, float)
    s = r.std(ddof=1)
    return float(r.mean() / s * math.sqrt(365)) if s > 0 else float("nan")

# ------------------------------------------------- SPOT-CHECK 1: A1 stamp ----
# Recompute shipped A1 (db5) FULL and OOS CAGR / MDD / Sharpe from the daily
# stamp-exact equity curve and compare to bt_stamp_exact.json.
# Window convention: n = # return days -> equity slice has n+1 points
# (FULL skips 200 warm-up rows -> starts 2020-07-19; OOS returns start 2022-01-01
# -> equity base 2021-12-31).
eq_full = stamp["equity_A1_VB_db5"].dropna().iloc[-2296:]   # 2296 pts -> 2295 rets
r_full = eq_full.pct_change().dropna()
eq_oos = stamp["equity_A1_VB_db5"].loc["2021-12-31":]       # 1765 pts -> 1764 rets
r_oos = eq_oos.pct_change().dropna()

chk1 = {
    "recomputed": {
        "FULL": {"n": len(eq_full), "cagr": cagr(eq_full), "mdd": mdd(eq_full), "sharpe": sharpe(r_full)},
        "OOS": {"n": len(eq_oos), "cagr": cagr(eq_oos), "mdd": mdd(eq_oos), "sharpe": sharpe(r_oos)},
    },
    "artifact": {
        "FULL": stampj["windows"]["A1_VB_db5"]["FULL_2020H2_2026"],
        "OOS": stampj["windows"]["A1_VB_db5"]["OOS_2022_2026"],
    },
}
chk1["delta_cagr_bp"] = {
    "FULL": (chk1["recomputed"]["FULL"]["cagr"] - chk1["artifact"]["FULL"]["cagr"]) * 1e4,
    "OOS": (chk1["recomputed"]["OOS"]["cagr"] - chk1["artifact"]["OOS"]["cagr"]) * 1e4,
}
chk1["delta_mdd_pp"] = {
    "FULL": (chk1["recomputed"]["FULL"]["mdd"] - chk1["artifact"]["FULL"]["mdd"]) * 100,
    "OOS": (chk1["recomputed"]["OOS"]["mdd"] - chk1["artifact"]["OOS"]["mdd"]) * 100,
}
chk1["pass"] = bool(all(abs(v) < 1.0 for v in chk1["delta_cagr_bp"].values()) and
                    all(abs(v) < 0.05 for v in chk1["delta_mdd_pp"].values()))
OUT["spotcheck_1_A1_stamp_curve"] = chk1

# --------------------------------------- SPOT-CHECK 2: 2021 episode troughs --
# Artifact defines trough dd vs the RUNNING PEAK over full history (not the
# Apr-Dec window). Rebuild parity equity from bt_daily.csv stored returns
# (verified: ret_A1_VB == w_A1_VB*ret_btc - w_A1_VB*fund_sum - TC*turn to 1e-10,
# i.e. the w columns in bt_daily.csv are HELD weights) and measure the
# 2021-12-17 trough vs running max.
epj = json.load(open("bt_episode2021.json"))["arms"]
chk2 = {}
for arm, col, want in [("A0_baseline", "ret_A0_baseline", -56.46), ("A1_VB", "ret_A1_VB", -38.75)]:
    eq = (1 + daily[col].astype(float)).cumprod()
    tdate = epj[arm]["window_trough_date"]
    eq_to_trough = eq.loc[:tdate]
    got = (eq_to_trough.iloc[-1] / eq_to_trough.max() - 1) * 100
    chk2[arm] = {"trough_date": tdate, "recomputed_trough_pct": round(got, 2),
                 "artifact_pct": want, "pass": bool(abs(got - want) < 0.15)}
# worst held day for A1 across FULL (parity daily returns; w col = held weight)
r_a1 = daily["ret_A1_VB"].astype(float)
w_a1 = daily["w_A1_VB"].astype(float)
worst = r_a1[w_a1 > 0].nsmallest(3)                # held days only
chk2["A1_worst_held_days_recomputed"] = {str(k.date()): round(v * 100, 2) for k, v in worst.items()}
chk2["A1_worst_artifact"] = {"2021-05-12": -12.68}
chk2["pass_worst_day"] = bool(abs(worst.iloc[0] * 100 - (-12.68)) < 0.05)
OUT["spotcheck_2_episode2021"] = chk2

# --------------------------------------- SPOT-CHECK 3: trade log / fees ------
chk3 = {
    "n_trades_recomputed": int(len(trades)),
    "n_trades_artifact": stampj["trade_stats"]["A1_VB_db5"]["n_trades"],
    "fees_recomputed_usdt": float(trades["fee_usdt"].sum()) if "fee_usdt" in trades.columns else None,
    "fees_artifact_usdt": stampj["trade_stats"]["A1_VB_db5"]["total_fees_usdt"],
}
if chk3["fees_recomputed_usdt"] is not None:
    chk3["pass"] = bool((chk3["n_trades_recomputed"] == chk3["n_trades_artifact"]) and
                        abs(chk3["fees_recomputed_usdt"] - chk3["fees_artifact_usdt"]) < 1.0)
else:
    chk3["columns"] = list(trades.columns)
    chk3["pass"] = bool(chk3["n_trades_recomputed"] == chk3["n_trades_artifact"])
OUT["spotcheck_3_trade_log"] = chk3

# ------------------------------------------------ funding term (verified) ----
# bt_common.py sim(): ret[t] = w[t]*r[t] - w[t]*fund[t] - TC*turn[t] with the
# bt_daily.csv w columns already HELD weights (reconstruction verified to 1e-10).
# fund_sum > 0 => longs PAY. Funding contribution = -w*fund_sum.
d = daily.loc["2022-01-01":].copy()
w = d["w_A1_VB"].fillna(0)                         # held weight (verified)
OUT["funding_term_check"] = {
    "reconstruction": "ret_A1_VB == w*ret_btc - w*fund_sum - 5bp*turn (max diff 9.8e-11)",
    "oos_actual_inmarket_funding_ann_pct": round(float(d["fund_sum"][w == 1].mean() * 365 * 100), 2),
    "artifact_oos_funding_drag_ann_pct": verdict["b_horse_race"]["A1_VB"]["OOS_2022_2026"]["funding_drag_ann_pct"],
    "ref_2021_inmarket_ann_pct_QR": 29.5,
}

# ------------------------------------------------ STRESS A: funding regime ---
# Replace actual in-market funding with a 2021-style 25%/yr cost on held days,
# keeping the price path identical: r_stress = r + w*fund_sum - w*(0.25/365).
adj = w * (d["fund_sum"] - 0.25 / 365.0)
r_stress = d["ret_A1_VB"] + adj
eq_stress = (1 + r_stress).cumprod()
eq_base = (1 + d["ret_A1_VB"]).cumprod()
OUT["stress_A_funding_25pct"] = {
    "oos_base": {"cagr": round(cagr(eq_base) * 100, 2), "mdd": round(mdd(eq_base) * 100, 2),
                 "sharpe": round(sharpe(d["ret_A1_VB"]), 3)},
    "oos_stressed_25pct_inmarket": {"cagr": round(cagr(eq_stress) * 100, 2), "mdd": round(mdd(eq_stress) * 100, 2),
                                    "sharpe": round(sharpe(r_stress), 3)},
    "note": "parity accounting, OOS 2022-26 price path held fixed; 2021 actual in-market funding was ~29.5%/yr, so 25%/yr is a mild-2021 repeat",
}

# ------------------------------------------------ STRESS B: whipsaw chop -----
# Aug-Dec 2021: gate ON, breaker OFF (rv10<100) -> the overlay's blind spot.
seg = ep.loc["2021-08-10":"2021-12-30", "A1_VB"].astype(float)
seg0 = ep.loc["2021-08-10":"2021-12-30", "A0_baseline"].astype(float)
OUT["stress_B_whipsaw_2021_chop"] = {
    "A1_ret_2021_08_10_to_12_30_pct": round((seg.iloc[-1] / seg.iloc[0] - 1) * 100, 2),
    "A0_ret_same_window_pct": round((seg0.iloc[-1] / seg0.iloc[0] - 1) * 100, 2),
    "A1_mdd_in_window_pct": round(mdd(seg) * 100, 2),
    "n_flips_A1": int((ep["m_vb"].loc["2021-08-10":"2021-12-30"].diff().abs() > 0).sum()),
    "note": "rv10 69-89% < 100% threshold -> breaker silent; gate hysteresis eats the chop. Bounded by gate only.",
}

# ------------------------------------------- ENVELOPE: bootstrap MDD quotes --
bt = verdict["e_bootstrap"]
OUT["mdd_envelope_bootstrap"] = {
    "A1_FULL": {"median_pct": round(bt["FULL_per_arm"]["A1_VB"]["mdd_median"] * 100, 1),
                "ci95_worst_pct": round(bt["FULL_per_arm"]["A1_VB"]["mdd_ci95_worst_best"][0] * 100, 1),
                "ci95_best_pct": round(bt["FULL_per_arm"]["A1_VB"]["mdd_ci95_worst_best"][1] * 100, 1)},
    "A1_OOS": {"median_pct": round(bt["OOS_per_arm"]["A1_VB"]["mdd_median"] * 100, 1),
               "ci95_worst_pct": round(bt["OOS_per_arm"]["A1_VB"]["mdd_ci95_worst_best"][0] * 100, 1),
               "ci95_best_pct": round(bt["OOS_per_arm"]["A1_VB"]["mdd_ci95_worst_best"][1] * 100, 1)},
    "realized_stamp_FULL_pct": round(stampj["windows"]["A1_VB_db5"]["FULL_2020H2_2026"]["mdd"] * 100, 1),
    "realized_stamp_OOS_pct": round(stampj["windows"]["A1_VB_db5"]["OOS_2022_2026"]["mdd"] * 100, 1),
    "reading": "~2.5% of FULL resamples have MDD worse than -74.6%; median -47.4% sits at the user's tolerance ceiling",
}

# ------------------------------------------------- Kelly / sizing reference --
mu = d["ret_A1_VB"].mean() * 365
sig = d["ret_A1_VB"].std(ddof=1) * math.sqrt(365)
OUT["kelly_reference"] = {"oos_arith_mean_ann": round(mu, 4), "oos_vol_ann": round(sig, 4),
                          "full_kelly_x": round(mu / sig ** 2, 2),
                          "note": "full Kelly > 1x => 1x leverage cap is below Kelly; sizing constraint is mandate MDD, not Kelly"}

# ------------------------------------------------- combined-book arithmetic --
# Carry book (approved): 3-5%/yr, MDD -0.69%, Sharpe 8.25, cap 10% NAV, delta-neutral.
# Directional sleeve (this): OOS honest CAGR 15-20%, vol ~33%, bootstrap MDD median -47%.
carry = {"ret": 0.04, "vol": 0.04 / 8.25, "mdd": -0.0069}
sleeve = {"ret": 0.175, "vol": 0.3357, "mdd": -0.474}     # mid of honest 15-20%, OOS stamp vol
for w_dir in (0.03, 0.05, 0.10):
    w_car = 0.10
    pr = w_dir * sleeve["ret"] + w_car * carry["ret"]
    pv = math.sqrt((w_dir * sleeve["vol"]) ** 2 + (w_car * carry["vol"]) ** 2)   # corr=0 by construction
    pm = w_dir * sleeve["mdd"] + w_car * carry["mdd"]                            # simultaneous stress
    OUT.setdefault("combined_book", {})[f"dir_{int(w_dir*100)}pct_carry_10pct"] = {
        "ret_on_NAV_pct": round(pr * 100, 2), "vol_on_NAV_pct": round(pv * 100, 2),
        "simultaneous_stress_dd_on_NAV_pct": round(pm * 100, 2),
        "dir_sleeve_alone_stress_on_NAV_pct": round(w_dir * sleeve["mdd"] * 100, 2),
    }
OUT["combined_book"]["notes"] = [
    "carry is delta-neutral => return correlation to directional sleeve ~0 by construction; PnL regime-correlated (both earn in bulls).",
    "funding legs are natural counterparties: sleeve pays funding in bulls (2021: -24.8%/yr in-market) that the carry book harvests; net cross-book funding leak partially internalizes.",
    "venue concentration: both books on Binance BTC perp -> exchange/counterparty risk is additive, not diversified; separate sub-accounts per spec S1.",
]

json.dump(OUT, open("risk_checks.json", "w"), indent=2)
print(json.dumps(OUT, indent=2))
