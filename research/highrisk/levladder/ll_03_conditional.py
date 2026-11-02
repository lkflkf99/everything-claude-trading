"""ll_03: TASK 3 — conditional leverage geometry.

The strategist's pre-designed arm (spec section 8): L = 1.5 iff gate=1 AND vb ON
AND rv10 <= 60%, else 1x. Inside holding episodes gate=1 and vb=ON by
construction, so the rule reduces to rv10(decision close) <= 0.60, effective
00:05 next day. Evaluated here on the actual path with full margin mechanics.

Extension grid for the question "does any simple causal rule make 2x or 3x
survivable": L(t) = Lmax iff rv10(t) <= X AND dd_from_episode_peak(t) > -Y,
else 1x. X in {0.50, 0.60, 0.70}, Y in {None, 0.15, 0.20}, Lmax in {2, 3}.
(Breaker state is vacuous inside episodes: vb OFF ends the episode by definition.)

Also reports: fraction of gate-on days with rv10 <= 60%, and the dodge analysis
for killer episodes (rv10 at entry vs kill timing from ll_02b).

Outputs: conditional_rules.csv, conditional_stats.json, book_cond_<name>.json
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "research/highrisk/levladder")
from ll_common import (OUT, Book, Path5m, load_daily, load_episodes, load_p05,
                       load_stamps)

daily = load_daily()
eps = load_episodes(daily)
path = Path5m()
stamps = load_stamps()
p05 = load_p05()

ARMS = [{"kind": "cond", "L": 1.5, "X": 0.60, "Y": None, "name": "strategist_1.5_rv60"}]
for Lmax in (1.5, 2.0, 3.0):
    for X in (0.50, 0.60, 0.70):
        for Y in (None, 0.15, 0.20):
            nm = f"L{Lmax}_rv{int(X*100)}" + (f"_dd{int(Y*100)}" if Y else "")
            ARMS.append({"kind": "cond", "L": Lmax, "X": X, "Y": Y, "name": nm})

rows = []
for arm in ARMS:
    b = Book(daily, eps, path, stamps, p05, arm).run()
    perf = b.perf(skip=200)
    art = {
        "arm": arm, "dead": b.dead, "death": b.death, "perf_full": perf,
        "funding_per_year": b.funding_per_year(), "n_trades": b.n_trades,
        "end_equity": b.end_equity, "flags": sorted(set(b.flags)),
        "ep_results": [{k: v for k, v in c.items() if k != "ep"} for c in b.ep_results],
        "equity": [[str(t.date()), float(v)] for t, v in b.equity_samples],
    }
    with open(f"{OUT}/book_cond_{arm['name']}.json", "w") as fh:
        json.dump(art, fh, default=str)
    worst_ep = min(b.ep_results, key=lambda c: c["minE_ratio"]) if b.ep_results else None
    rows.append({
        "arm": arm["name"], "L_max": arm["L"], "rv10_X": arm["X"], "dd_Y": arm["Y"],
        "dead": b.dead,
        "kill_ep": b.death.get("episode") if b.death else None,
        "kill_time": b.death.get("time") if b.death else None,
        "FULL_cagr_pct": round(100 * perf["cagr"], 2),
        "FULL_mdd_pct": round(100 * perf["mdd"], 2),
        "FULL_sharpe": round(perf["sharpe"], 3),
        "n_trades": b.n_trades,
        "worst_ep_min_ratio": round(worst_ep["minE_ratio"], 4) if worst_ep else None,
        "worst_ep": worst_ep["ep_id"] if worst_ep else None,
        "end_equity": round(b.end_equity, 0),
    })
df = pd.DataFrame(rows)
df.to_csv(f"{OUT}/conditional_rules.csv", index=False)

# ------------------------------------------------ conditional stats + dodge table
gate_on = daily[daily["gate"] == 1]
frac_rv60 = float((gate_on["rv10"] <= 0.60).mean())
frac_rv50 = float((gate_on["rv10"] <= 0.50).mean())
frac_rv70 = float((gate_on["rv10"] <= 0.70).mean())

exc = pd.read_csv(f"{OUT}/episodes_excursions.csv")
kills = pd.read_csv(f"{OUT}/ladder_by_episode.csv")
kill_map = kills[kills["liquidated"]].groupby("ep")["L"].apply(list).to_dict()
dodge = []
for _, e in exc.iterrows():
    Ls = kill_map.get(e["ep"], [])
    dodge.append({
        "ep": e["ep"], "entry_day": e["entry_day"],
        "kills_L": Ls,
        "rv10_at_entry": e["rv10_at_entry"],
        "rv10_le_60_at_entry": e["rv10_le_60_at_entry"],
        "enters_leveraged_under_rv60": bool(e["rv10_le_60_at_entry"]),
        "first_rv10_gt60_decision": e["first_rv10_gt60"],
        "worst_time": e["worst_time"],
    })
stats = {
    "gate_on_days": int(len(gate_on)),
    "frac_gate_on_rv10_le_50": round(frac_rv50, 4),
    "frac_gate_on_rv10_le_60": round(frac_rv60, 4),
    "frac_gate_on_rv10_le_70": round(frac_rv70, 4),
    "dodge_table": dodge,
}
with open(f"{OUT}/conditional_stats.json", "w") as fh:
    json.dump(stats, fh, indent=2, default=str)

print(df.to_string(index=False))
print(f"\ngate-on days: {len(gate_on)}; rv10<=60%: {frac_rv60:.1%}; "
      f"<=50%: {frac_rv50:.1%}; <=70%: {frac_rv70:.1%}")
