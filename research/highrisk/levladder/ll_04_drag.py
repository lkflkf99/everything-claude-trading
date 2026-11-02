"""ll_04: TASK 4 — drag scaling + consolidated arm re-run (with fee tracking).

(a) Re-runs every arm (constants, strategist, conditional grid, and supplemental
    5x/10x conditional arms for the dodge question) with fee accounting and saves
    arms_summary.csv + book_<name>.json for ll_05.

(b) Drag table: funding and fees scale with notional = L x margin.
    - in-market funding per year (2021 / 2024 / 2026 regimes, FULL, OOS) per unit
      of notional, from real 8h stamps on held windows; at L it is L x that.
    - taker cost: 5bp x L per side per unit of equity; realized per-arm fee drag
      from the sims (conditional arms toggle -> superlinear fees).
    - break-even gross held return g* = f + c (per notional-year); leverage L is
      net-positive iff g > f + c. Realized g computed on held days (bt_daily).

Outputs: arms_summary.csv, drag_scaling.csv, book_*.json
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "research/highrisk/levladder")
from ll_common import (OUT, Book, Path5m, load_daily, load_episodes, load_p05,
                       load_stamps, static_lp_distance, TC)

daily = load_daily()
eps = load_episodes(daily)
path = Path5m()
stamps = load_stamps()
p05 = load_p05()

# ------------------------------------------------------------------ arm re-run
ARMS = [{"kind": "const", "L": L, "X": None, "Y": None, "name": f"const_{L}"}
        for L in (1.0, 1.5, 2.0, 3.0, 5.0, 10.0)]
ARMS.append({"kind": "cond", "L": 1.5, "X": 0.60, "Y": None, "name": "strategist_1.5_rv60"})
for Lmax in (1.5, 2.0, 3.0):
    for X in (0.50, 0.60, 0.70):
        for Y in (None, 0.15, 0.20):
            nm = f"L{Lmax}_rv{int(X*100)}" + (f"_dd{int(Y*100)}" if Y else "")
            ARMS.append({"kind": "cond", "L": Lmax, "X": X, "Y": Y, "name": nm})
for Lmax, X in ((5.0, 0.50), (5.0, 0.60), (10.0, 0.50), (10.0, 0.60)):
    ARMS.append({"kind": "cond", "L": Lmax, "X": X, "Y": None,
                 "name": f"L{Lmax}_rv{int(X*100)}"})

rows = []
for arm in ARMS:
    b = Book(daily, eps, path, stamps, p05, arm).run()
    perf = b.perf(skip=200)
    eq = b.equity_curve()
    oos = eq["2022-01-01":]
    yrs = len(oos) / 365.0
    oos_cagr = float((oos.iloc[-1] / oos.iloc[0]) ** (1 / yrs) - 1) if len(oos) > 2 else np.nan
    oos_mdd = float((oos / oos.cummax() - 1).min()) if len(oos) > 2 else np.nan
    art = {
        "arm": arm, "dead": b.dead, "death": b.death, "perf_full": perf,
        "oos_cagr": oos_cagr, "oos_mdd": oos_mdd,
        "funding_per_year": b.funding_per_year(), "n_trades": b.n_trades,
        "fees_total": b.fees_total, "end_equity": b.end_equity,
        "flags": sorted(set(b.flags)),
        "ep_results": [{k: v for k, v in c.items() if k != "ep"} for c in b.ep_results],
        "equity": [[str(t.date()), float(v)] for t, v in b.equity_samples],
    }
    with open(f"{OUT}/book_{arm['name']}.json", "w") as fh:
        json.dump(art, fh, default=str)
    rows.append({
        "arm": arm["name"], "kind": arm["kind"], "L_max": arm["L"],
        "rv10_X": arm["X"], "dd_Y": arm["Y"],
        "dead": b.dead,
        "kill_ep": b.death.get("episode") if b.death else None,
        "kill_time": b.death.get("time") if b.death else None,
        "FULL_cagr_pct": round(100 * perf["cagr"], 2),
        "FULL_mdd_pct": round(100 * perf["mdd"], 2),
        "FULL_sharpe": round(perf["sharpe"], 3),
        "OOS_cagr_pct": round(100 * oos_cagr, 2),
        "OOS_mdd_pct": round(100 * oos_mdd, 2),
        "n_trades": b.n_trades,
        "fees_total_usdt": round(b.fees_total, 2),
        "end_equity": round(b.end_equity, 0),
    })
summary = pd.DataFrame(rows)
summary.to_csv(f"{OUT}/arms_summary.csv", index=False)

# ------------------------------------------------------------------ drag table
# held windows from the shipped episodes (stamp held if position open at the stamp)
windows = [(ep["entry_exec_day"] + pd.Timedelta(minutes=5),
            (ep["exit_exec_day"] + pd.Timedelta(minutes=5))
            if ep["exit_exec_day"] is not None else pd.Timestamp("2026-11-01"))
           for ep in eps]
st = stamps.reset_index()
st["day"] = st["funding_time_utc"].dt.normalize()
held = np.zeros(len(st), dtype=bool)
ts = st["funding_time_utc"].values
for a, b_ in windows:
    held |= (ts >= np.datetime64(a)) & (ts < np.datetime64(b_))
st["held"] = held
st["year"] = st["day"].dt.year

def inmarket_funding(year):
    s = st[st["year"] == year]
    h = s[s["held"]]
    if len(h) == 0:
        return np.nan, 0
    # annualized per-notional rate while held (mean stamp rate x 3 x 365)
    return float(h["funding_rate"].mean() * 3 * 365), int(len(h))

regimes = {}
for y in (2020, 2021, 2023, 2024, 2025, 2026):
    r, n = inmarket_funding(y)
    regimes[str(y)] = {"inmarket_funding_ann_pct": round(100 * r, 2) if np.isfinite(r) else None,
                       "held_stamps": n}
# FULL / OOS on the daily series (held rows via w shift, bt_common convention)
w = daily["gate"] * daily["m_vb"]
wh = w.shift(1).fillna(0.0)
held_rows = wh > 0.5
full = daily.iloc[200:]
oos = daily.loc["2022-01-01":]
def g_f(rows):
    h = rows[held_rows.loc[rows.index]]
    g = float(rows["ret_btc"][held_rows.loc[rows.index]].mean() * 365)
    f = float(rows["fund_sum"][held_rows.loc[rows.index]].mean() * 365)
    return g, f, int(held_rows.loc[rows.index].sum())
g_full, f_full, nh_full = g_f(full)
g_oos, f_oos, nh_oos = g_f(oos)
regimes["FULL"] = {"inmarket_funding_ann_pct": round(100 * f_full, 2), "held_days": nh_full,
                   "gross_held_g_ann_pct": round(100 * g_full, 2)}
regimes["OOS"] = {"inmarket_funding_ann_pct": round(100 * f_oos, 2), "held_days": nh_oos,
                  "gross_held_g_ann_pct": round(100 * g_oos, 2)}

COST_ANN_1X = 0.0045   # shipped A1 cost drag 0.45%/yr FULL (bt_verdict b_horse_race)
drag_rows = []
for L in (1.0, 1.5, 2.0, 3.0, 5.0, 10.0):
    arm = summary[summary["arm"] == f"const_{L}"].iloc[0]
    with open(f"{OUT}/book_const_{L}.json") as fh:
        bk = json.load(fh)
    eqv = pd.Series({t: v for t, v in bk["equity"]})
    yrs_full = len(daily.iloc[200:]) / 365.0
    fee_drag = arm["fees_total_usdt"] / float(eqv.mean()) / yrs_full  # per mean equity
    r = {
        "L": L,
        "lp_dist_pct": round(100 * static_lp_distance(L), 2),
        "fund_inmarket_2021_pct": round(L * regimes["2021"]["inmarket_funding_ann_pct"], 1),
        "fund_inmarket_2024_pct": round(L * regimes["2024"]["inmarket_funding_ann_pct"], 1),
        "fund_inmarket_2026_pct": round(L * regimes["2026"]["inmarket_funding_ann_pct"], 1),
        "fund_inmarket_FULL_pct": round(L * f_full * 100, 1),
        "fund_inmarket_OOS_pct": round(L * f_oos * 100, 1),
        "taker_per_roundtrip_pct": round(100 * 2 * TC * L, 2),
        "fee_drag_ann_pct_sim": round(100 * fee_drag, 2),
        "breakeven_g_inmarket_FULL_pct": round(100 * (f_full + COST_ANN_1X), 1),
        "breakeven_g_inmarket_OOS_pct": round(100 * (f_oos + COST_ANN_1X), 1),
        "gross_g_FULL_pct": round(100 * g_full, 1),
        "gross_g_OOS_pct": round(100 * g_oos, 1),
        "net_uplift_per_unit_FULL_pct": round(100 * (L - 1) * (g_full - f_full - COST_ANN_1X), 1),
        "net_uplift_per_unit_OOS_pct": round(100 * (L - 1) * (g_oos - f_oos - COST_ANN_1X), 1),
        "sim_FULL_cagr_pct": arm["FULL_cagr_pct"],
        "sim_FULL_mdd_pct": arm["FULL_mdd_pct"],
        "sim_DEAD": bool(arm["dead"]),
    }
    drag_rows.append(r)
drag = pd.DataFrame(drag_rows)
drag.to_csv(f"{OUT}/drag_scaling.csv", index=False)
with open(f"{OUT}/drag_regimes.json", "w") as fh:
    json.dump(regimes, fh, indent=2)

print(drag.to_string(index=False))
print("\nregimes:", json.dumps(regimes, indent=2))
print("\nsupplemental 5x/10x conditional arms:")
print(summary[summary["arm"].str.startswith(("L5", "L10"))].to_string(index=False))
