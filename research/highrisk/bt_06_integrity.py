"""bt_06: INTEGRITY BATTERY + CONSOLIDATED VERDICT.

- worst held days per arm (net daily ret while wh>0, top 5)
- trade-count / turnover stats (QR-parity + stamp-exact A1 log)
- funding paid per year (stamp-exact, shipped config + A0)
- blocked-days metric reconciliation (strategist's 5.8% basis)
- deflated Sharpe ratio (Bailey & Lopez de Prado) given the selection ledger
- consolidated selection-rule verdict -> bt_verdict.json
"""
import pandas as pd, numpy as np, json, sys
from math import erf, sqrt, pi, exp
sys.path.insert(0, "research/highrisk")
from bt_common import OUT, TC
from qr_utils import perf_stats

daily = pd.read_csv(f"{OUT}/bt_daily.csv", index_col=0, parse_dates=True)
idx = daily.index
ARMS = ["A0_baseline", "A1_VB", "A2_TS30", "A3_VB_TS"]
out = {}

# ---------- worst held days ----------
wh_days = {}
for a in ARMS:
    wh = daily[f"w_{a}"].values
    rr = daily[f"ret_{a}"].values
    held = wh > 0.5
    order = np.argsort(rr[held])[:5]
    dates = idx[held][order]
    wh_days[a] = [{"date": str(d.date()), "net_ret_pct": round(100 * float(rr[held][j]), 2)}
                  for d, j in zip(dates, order)]
out["worst_held_days"] = wh_days

# ---------- trade / turnover stats (QR-parity, FULL window) ----------
mfull = np.zeros(len(idx), bool); mfull[200:] = True
mfull &= (idx >= "2020-01-01") & (idx <= "2026-10-31")
yrs_full = mfull.sum() / 365.0
tstats = {}
for a in ARMS:
    turn = daily[f"turn_{a}"].values
    wh = daily[f"w_{a}"].values
    trades = turn[mfull] > 1e-12
    tstats[a] = {
        "n_trade_days_FULL": int(trades.sum()),
        "round_trips_FULL": int(((wh[mfull] > 0.5) & (np.concatenate([[0.0], wh[:-1]])[mfull] < 0.5)).sum()),
        "turnover_ann_FULL": round(float(turn[mfull].mean() * 365), 2),
        "cost_drag_bp_per_yr_FULL": round(1e4 * float((turn[mfull] * TC).mean() * 365), 1),
        "flip_trades_pct": round(100 * float((turn[mfull][trades] > 0.5).mean()), 1),
    }
out["trade_stats_qr_parity_FULL"] = tstats
tl = pd.read_csv(f"{OUT}/bt_trade_log.csv")
out["trade_stats_stamp_exact_A1"] = {"n_trades_FULL_span": int(len(tl)),
                                     "total_fees_usdt": round(float(tl["fee_usdt"].sum()), 2)}

# ---------- blocked-days reconciliation ----------
gate = daily["gate"].values
mvb = daily["m_vb"].values
blocked_decided = int(((mvb == 0) & (gate == 1)).sum())
gate_on_panel = int((gate == 1).sum())
wh1 = daily["w_A1_VB"].values
gate_held = np.concatenate([[0.0], gate[:-1]])
blocked_held_full = int(((wh1[mfull] < 0.5) & (gate_held[mfull] > 0.5)).sum())
gate_held_on_full = int((gate_held[mfull] > 0.5).sum())
out["blocked_reconciliation"] = {
    "decided_space_panel": {"blocked": blocked_decided, "gate_on": gate_on_panel,
                            "pct": round(100 * blocked_decided / gate_on_panel, 2)},
    "held_space_FULL": {"blocked": blocked_held_full, "gate_on": gate_held_on_full,
                        "pct": round(100 * blocked_held_full / gate_held_on_full, 2)},
    "strategist_basis_pct": 5.8,
}

# ---------- funding per year (stamp-exact) ----------
se = json.load(open(f"{OUT}/bt_stamp_exact.json"))
out["funding_per_year_stamp_exact"] = se["funding_per_year"]

# ---------- deflated Sharpe ----------
def norm_cdf(x):
    return 0.5 * (1 + erf(x / sqrt(2)))
def norm_ppf(p):
    # Acklam inverse normal CDF
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
        q = sqrt(-2 * np.log(p))
        num = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        den = ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        return num / den
    if p > phigh:
        q = sqrt(-2 * np.log(1 - p))
        num = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        den = ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        return -num / den
    q = p - 0.5
    r = q * q
    num = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
    den = (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    return num / den

# trial family: OOS Sharpes of every strategy-level config tested across the pipeline
family = {"BH_spot": 0.464, "VT": 0.350, "TG1x_plain": 0.757, "VT_TG": 0.672,
          "VT_TG150": 0.621, "VT_TG250": 0.445, "VT_MOM12M": 0.680,
          "A0_TG1x_hyst2": 0.7543, "A1_VB_100_5": 0.7261, "A2_TS30": 0.7543, "A3_VB_TS": 0.7261}
vb = pd.read_csv(f"{OUT}/bt_sensitivity_vb.csv")
for _, row in vb.iterrows():
    family[f"VB_X{int(row['X_pct'])}_k{int(row['k'])}"] = float(row["OOS_2022_2026_sharpe"])
tss = pd.read_csv(f"{OUT}/bt_sensitivity_ts.csv")
for _, row in tss.iterrows():
    family[f"TS_tau{int(row['tau_pct'])}"] = float(row["OOS_2022_2026_sharpe"])
sharpes = np.array(list(family.values()))
N = len(sharpes)
V_N = float(np.var(sharpes, ddof=1))
gamma_em = 0.5772156649
sr_star_ann = sqrt(V_N) * ((1 - gamma_em) * norm_ppf(1 - 1 / N) +
                           gamma_em * norm_ppf(1 - 1 / (N * exp(1))))
m_oos = (idx >= "2022-01-01") & (idx <= "2026-10-31")
dsr = {}
for a, lbl in [("A0_baseline", "A0"), ("A1_VB", "A1")]:
    rr = daily[f"ret_{a}"].values[m_oos]
    n = len(rr)
    mu, sd = rr.mean(), rr.std(ddof=1)
    sr_d = mu / sd
    g3 = float(((rr - mu) ** 3).mean() / sd ** 3)
    g4 = float(((rr - mu) ** 4).mean() / sd ** 4)
    sr_star_d = sr_star_ann / sqrt(365)
    num = (sr_d - sr_star_d) * sqrt(n - 1)
    den = sqrt(max(1e-12, 1 - g3 * sr_d + (g4 - 1) / 4 * sr_d ** 2))
    dsr[lbl] = {"sharpe_ann": round(sr_d * sqrt(365), 3), "skew": round(g3, 2),
                "excess_kurt": round(g4 - 3, 2), "dsr": round(norm_cdf(num / den), 4)}
out["deflated_sharpe"] = {
    "trial_family_size_N": N, "trial_family": {k: round(v, 3) for k, v in family.items()},
    "var_of_trial_sharpes": round(V_N, 4),
    "SR_star_ann_expected_max_under_null": round(sr_star_ann, 3),
    "results": dsr,
    "note": ("Bailey-Lopez de Prado DSR. Trial family = every strategy-level config tested in "
             "this pipeline (QR horse race + robustness + hysteresis + BT arms + VB/TS surfaces), "
             "N=30, positively correlated trials -> DSR is conservative on V_N but the family "
             "excludes QR's two DEAD overlay research lines (funding-contrarian, taker-flow), "
             "which would add ~2-6 more effective trials."),
}
with open(f"{OUT}/bt_integrity.json", "w") as fh:
    json.dump(out, fh, indent=2)
print(json.dumps(out, indent=2))
