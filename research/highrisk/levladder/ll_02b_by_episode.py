"""ll_02b: TASK 2 (cont.) — WHICH episodes kill WHICH leverage.

The chained sim (ll_02) kills the book at the FIRST killer episode and cannot see
later killers. Here each episode is re-run STANDALONE (fresh 10k book at episode
entry, same margin/deadband/funding mechanics) so every episode gets its own
verdict per L. This is the episode-by-episode liquidation map.

Output: ladder_by_episode.csv (ep x L grid: liquidated?, kill time, min equity
ratio, funding bleed, LP distance at entry, tier at entry).
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "research/highrisk/levladder")
from ll_common import (Book, Path5m, load_daily, load_episodes, load_p05,
                       load_stamps, static_lp_distance, tier_for, OUT)

daily = load_daily()
eps = load_episodes(daily)
path = Path5m()
stamps = load_stamps()
p05 = load_p05()

LEVS = [1.0, 1.5, 2.0, 3.0, 5.0, 10.0]
rows = []
for ep in eps:
    for L in LEVS:
        arm = {"kind": "const", "L": L, "X": None, "Y": None,
               "name": f"ep{ep['id']}_L{L}"}
        b = Book(daily, [ep], path, stamps, p05, arm).run()
        c = b.ep_results[0] if b.ep_results else None
        mmr, _ = tier_for(L * ep["entry_notional"])
        rows.append({
            "ep": ep["id"],
            "entry_day": str(ep["entry_exec_day"].date()),
            "L": L,
            "liquidated": bool(b.dead and b.death and "lp" in b.death),
            "dust_or_neg": bool(b.dead and b.death and "lp" not in b.death),
            "kill_time": b.death.get("time") if b.death else None,
            "lp_dist_pct_at_entry": round(100 * static_lp_distance(L, mmr), 2),
            "tier_at_entry": 2 if L * ep["entry_notional"] > 300_000 else 1,
            "min_equity_ratio": round(c["minE_ratio"], 4) if c else np.nan,
            "funding_pct_of_E0": round(100 * c["funding"] / c["E_entry"], 2) if c else np.nan,
            "rebalances": c["rebalances"] if c else None,
        })
df = pd.DataFrame(rows)
df.to_csv(f"{OUT}/ladder_by_episode.csv", index=False)

piv = df.pivot_table(index=["ep", "entry_day"], columns="L", values="liquidated")
print("Liquidated (standalone episode sims):")
print(piv.astype(int).to_string())
print("\nMin equity ratio (worst within-episode equity / episode-start equity):")
piv2 = df.pivot_table(index=["ep", "entry_day"], columns="L", values="min_equity_ratio")
print(piv2.to_string())
print("\nKills:")
print(df[df["liquidated"] | df["dust_or_neg"]].to_string(index=False))
