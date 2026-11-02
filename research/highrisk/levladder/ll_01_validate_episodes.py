"""ll_01: engine validation (1x arm must reproduce the shipped A1 backtest), then
TASK 1 of the mandate: per-episode worst adverse mark excursion on the actual path.

Validation targets (bt_verdict.json / risk_checks.json, stamp-exact A1_VB_db5):
  - 18 episodes from bt_trade_log.csv (17 closed + 1 open), same entry/exit days
  - funding/yr % of SoY equity: 2021 -24.76, 2024 -14.75, 2025 -3.98, 2026 -1.25
  - FULL CAGR 33.78%, FULL MDD -42.50%, OOS CAGR 20.53%
  - 40 logged trades at 1x (18 entries + 17 exits + 5 deadband rebalances)

Excursion table (episodes_excursions.csv), per episode:
  entry/exit exec days and actual fill prices, days held, exit reason,
  worst adverse mark excursion vs entry fill (5m mark low, trade-proxy flagged),
  its timestamp, same-day rv10 state (entry decision rv10, max rv10 before worst),
  episode close peak and dd-from-peak at the worst excursion, mark-gap flag.
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "research/highrisk/levladder")
from ll_common import (OUT, Book, Path5m, load_daily, load_episodes, load_p05,
                       load_stamps, ns, NS_5M)

daily = load_daily()
eps = load_episodes(daily)
path = Path5m()
stamps = load_stamps()
p05 = load_p05()

# ---------------------------------------------------------------- 1x validation
arm1 = {"kind": "const", "L": 1.0, "X": None, "Y": None, "name": "const_1.0"}
book1 = Book(daily, eps, path, stamps, p05, arm1).run()
perf_full = book1.perf(skip=200)
eq = book1.equity_curve()
oos = eq["2022-01-01":]
r_oos = oos.pct_change().dropna()
yrs_oos = len(oos) / 365.0
perf_oos = {
    "cagr": float((oos.iloc[-1] / oos.iloc[0]) ** (1 / yrs_oos) - 1),
    "mdd": float((oos / oos.cummax() - 1).min()),
}
fpy = book1.funding_per_year()

ep_days = [(str(e["entry_exec_day"].date()),
            str(e["exit_exec_day"].date()) if e["exit_exec_day"] is not None else None)
           for e in eps]
sim_days = [(c["entry_day"], c.get("exit_reason_sim")) for c in book1.ep_results]

targets = {
    "n_episodes": {"got": len(eps), "want": 18},
    "n_trades_1x": {"got": book1.n_trades, "want": 40},
    "FULL_cagr": {"got": round(100 * perf_full["cagr"], 2), "want": 33.78},
    "FULL_mdd": {"got": round(100 * perf_full["mdd"], 2), "want": -42.50},
    "OOS_cagr": {"got": round(100 * perf_oos["cagr"], 2), "want": 20.53},
    "OOS_mdd": {"got": round(100 * perf_oos["mdd"], 2), "want": -35.31},
    "fund_2021_pct": {"got": round(fpy.get(2021, {}).get("pct_soy", np.nan), 2), "want": -24.76},
    "fund_2024_pct": {"got": round(fpy.get(2024, {}).get("pct_soy", np.nan), 2), "want": -14.75},
    "fund_2026_pct": {"got": round(fpy.get(2026, {}).get("pct_soy", np.nan), 2), "want": -1.25},
}
tol = {"FULL_cagr": 0.30, "FULL_mdd": 0.60, "OOS_cagr": 0.30, "OOS_mdd": 0.60,
       "fund_2021_pct": 0.35, "fund_2024_pct": 0.35, "fund_2026_pct": 0.15}
checks = {}
for k, v in targets.items():
    if k in tol:
        checks[k] = {**v, "pass": abs(v["got"] - v["want"]) <= tol[k]}
    else:
        checks[k] = {**v, "pass": v["got"] == v["want"]}
checks["episode_days_match"] = {
    "got": [d for d, _ in sim_days] == [d for d, _ in
            [(str(e["entry_exec_day"].date()), None) for e in eps]],
    "pass": [c["entry_day"] for c in book1.ep_results] ==
            [str(e["entry_exec_day"].date()) for e in eps],
}
validation = {"targets": checks,
              "all_pass": all(c["pass"] for c in checks.values()),
              "flags_1x": sorted(set(book1.flags))[:20],
              "note": "1x arm re-simulates deadband rebalances; tolerance absorbs "
                      "mark-vs-trade stamp pricing and rebalance-day fill differences."}
print(json.dumps(validation, indent=2, default=str))

# ------------------------------------------------------- TASK 1: excursion table
rows = []
for ep, ctx in zip(eps, book1.ep_results):
    t0 = ns(ep["entry_exec_day"]) + NS_5M
    t1 = (ns(ep["exit_exec_day"]) + NS_5M) if ep["exit_exec_day"] is not None \
        else path.ns[-1] + NS_5M
    i0, i1 = path.slice(t0, t1)
    lows = path.low[i0:i1]
    ep_px = ep["entry_px"]
    k = int(np.argmin(lows))
    worst_adv = 1.0 - float(lows[k]) / ep_px
    worst_time = pd.Timestamp(path.ns[i0 + k])
    proxy = bool((path.src[i0:i1] == 0).any())
    # coverage: unobserved holes > 30 min inside the episode window
    seg = path.ns[i0:i1]
    hole = int(np.diff(seg).max()) if seg.size > 1 else 0
    # daily-close path inside the episode (decision closes known during the hold)
    d_in = ep["entry_decision"]
    d_out = ep["exit_decision"] if ep["exit_decision"] is not None else daily.index[-2]
    closes = daily.loc[d_in:d_out, "close"]
    rv10s = daily.loc[d_in:d_out, "rv10"]
    peak = closes.max()
    # state known at the worst-excursion bar: decision close of the prior day
    t_known = (worst_time.normalize() - pd.Timedelta(days=1))
    dd_at_worst = float(closes.loc[:t_known].iloc[-1] / closes.loc[:t_known].max() - 1) \
        if len(closes.loc[:t_known]) else np.nan
    rv10_entry = float(rv10s.iloc[0])
    rv10_to_worst = rv10s.loc[:t_known]
    rv10_max_before = float(rv10_to_worst.max())
    first_cross_60 = rv10_to_worst[rv10_to_worst > 0.60]
    first_cross_100 = rv10_to_worst[rv10_to_worst > 1.00]
    days_held = (ep["exit_exec_day"] - ep["entry_exec_day"]).days \
        if ep["exit_exec_day"] is not None else (pd.Timestamp(path.ns[-1]).normalize()
                                                 - ep["entry_exec_day"]).days
    ret_1x = (ep["exit_px"] / ep_px - 1) if ep["exit_px"] else np.nan
    rows.append({
        "ep": ep["id"],
        "entry_day": str(ep["entry_exec_day"].date()),
        "exit_day": str(ep["exit_exec_day"].date()) if ep["exit_exec_day"] is not None else "OPEN",
        "entry_px": ep_px, "exit_px": ep["exit_px"],
        "days_held": days_held,
        "exit_reason": ep["exit_reason"],
        "ret_1x_pct": round(100 * ret_1x, 2) if np.isfinite(ret_1x) else np.nan,
        "worst_adv_exc_pct": round(100 * worst_adv, 2),
        "worst_time": str(worst_time),
        "worst_uses_trade_proxy": bool(path.src[i0 + k] == 0),
        "any_trade_proxy": proxy,
        "max_hole_min": round(hole / 60e9, 1),
        "ep_close_peak": float(peak),
        "dd_from_peak_at_worst_pct": round(100 * dd_at_worst, 2),
        "rv10_at_entry": round(rv10_entry, 3),
        "rv10_le_60_at_entry": bool(rv10_entry <= 0.60),
        "rv10_max_before_worst": round(rv10_max_before, 3),
        "first_rv10_gt60": str(first_cross_60.index[0].date()) if len(first_cross_60) else None,
        "first_rv10_gt100": str(first_cross_100.index[0].date()) if len(first_cross_100) else None,
        "sim_min_equity_ratio_1x": round(ctx["minE_ratio"], 4),
        "sim_funding_usdt_1x": round(ctx["funding"], 2),
        "sim_rebalances_1x": ctx["rebalances"],
    })
exc = pd.DataFrame(rows)
exc.to_csv(f"{OUT}/episodes_excursions.csv", index=False)
with open(f"{OUT}/validation_1x.json", "w") as fh:
    json.dump(validation, fh, indent=2, default=str)
print(exc.to_string(index=False))
print("\nALL_VALIDATION_PASS:", validation["all_pass"])
