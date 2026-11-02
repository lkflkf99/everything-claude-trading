"""ll_02: TASK 2 — liquidation ladder on the gate's ACTUAL path.

Two screens per L in {1.5, 2, 3, 5, 10}:
  (a) STATIC: per-episode worst adverse mark excursion vs entry fill (ll_01 table)
      compared against the entry-time LP distance (1/L - MMR)/(1 - MMR), with a
      funding-bleed note (WB shrinks over the hold, pulling LP closer).
  (b) DYNAMIC (primary): the chained margin sim (ll_common.Book) with the shipped
      deadband mechanics, real funding stamps, tier-aware MMR. A book is KILLED at
      rung L if any episode liquidates (or dust-closes) on the actual path.

Outputs: ladder_static.csv, ladder_dynamic.csv, ladder_dynamic_episodes.csv,
         book_const_<L>.json (per-arm artifacts for ll_04/ll_05).
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "research/highrisk/levladder")
from ll_common import (OUT, Book, Path5m, load_daily, load_episodes, load_p05,
                       load_stamps, static_lp_distance, tier_for)

daily = load_daily()
eps = load_episodes(daily)
path = Path5m()
stamps = load_stamps()
p05 = load_p05()
exc = pd.read_csv(f"{OUT}/episodes_excursions.csv")

LEVS = [1.5, 2.0, 3.0, 5.0, 10.0]

# ---------------------------------------------------------- (a) static screen
st = []
ep_notional = {ep["id"]: ep["entry_notional"] for ep in eps}  # 1x logged notional ~ equity
for L in LEVS:
    d0 = static_lp_distance(L)
    for _, e in exc.iterrows():
        mmr2, _ = tier_for(L * ep_notional[e["ep"]])
        st.append({
            "L": L, "ep": e["ep"],
            "entry_day": e["entry_day"],
            "lp_dist_pct_tier1": round(100 * d0, 2),
            "lp_dist_pct_actual_tier": round(100 * static_lp_distance(L, mmr2), 2),
            "tier_at_entry": 2 if L * ep_notional[e["ep"]] > 300_000 else 1,
            "worst_adv_exc_pct": e["worst_adv_exc_pct"],
            "static_breach": bool(e["worst_adv_exc_pct"] / 100 >= d0),
        })
static_df = pd.DataFrame(st)
static_sum = (static_df.groupby("L")
              .agg(n_breach=("static_breach", "sum"),
                   worst_exc_pct=("worst_adv_exc_pct", "max")))
static_sum["lp_dist_pct"] = [round(100 * static_lp_distance(L), 2) for L in static_sum.index]
static_df.to_csv(f"{OUT}/ladder_static.csv", index=False)

# ---------------------------------------------------------- (b) dynamic sims
dyn_rows = []
ep_rows = []
for L in [1.0] + LEVS:
    arm = {"kind": "const", "L": L, "X": None, "Y": None, "name": f"const_{L}"}
    b = Book(daily, eps, path, stamps, p05, arm).run()
    perf = b.perf(skip=200)
    fpy = b.funding_per_year()
    death = b.death
    art = {
        "arm": arm["name"], "dead": b.dead, "death": death,
        "perf_full": perf, "funding_per_year": fpy,
        "n_trades": b.n_trades, "end_equity": b.end_equity,
        "flags": sorted(set(b.flags)),
        "ep_results": [{k: v for k, v in c.items() if k != "ep"} for c in b.ep_results],
        "equity": [[str(t.date()), float(v)] for t, v in b.equity_samples],
    }
    with open(f"{OUT}/book_const_{L}.json", "w") as fh:
        json.dump(art, fh, default=str)
    kill_ep = death.get("episode") if death else None
    dyn_rows.append({
        "L": L, "dead": b.dead,
        "kill_ep": kill_ep,
        "kill_time": death.get("time") if death else None,
        "kill_where": death.get("where") if death else None,
        "kill_lp": death.get("lp") if death else None,
        "kill_mark_low": death.get("mark_low") if death else None,
        "FULL_cagr_pct": round(100 * perf["cagr"], 2),
        "FULL_mdd_pct": round(100 * perf["mdd"], 2),
        "FULL_sharpe": round(perf["sharpe"], 3),
        "naive_Lx_mdd_pct": round(100 * L * -0.4250, 1),
        "n_trades": b.n_trades,
        "end_equity": round(b.end_equity, 2),
    })
    for c in b.ep_results:
        ep_rows.append({
            "L": L, "ep": c["ep_id"],
            "entry_day": c["entry_day"],
            "exit_reason_sim": c["exit_reason_sim"],
            "min_equity_ratio": round(c["minE_ratio"], 4),
            "funding_usdt": round(c["funding"], 2),
            "rebalances": c["rebalances"],
        })

dyn = pd.DataFrame(dyn_rows)
dyn.to_csv(f"{OUT}/ladder_dynamic.csv", index=False)
pd.DataFrame(ep_rows).to_csv(f"{OUT}/ladder_dynamic_episodes.csv", index=False)

print("STATIC (excursion vs entry-time LP distance, no rebalancing/funding bleed):")
print(static_sum.to_string())
print("\nDYNAMIC (chained margin sim, shipped deadband mechanics, real funding):")
print(dyn.to_string(index=False))
