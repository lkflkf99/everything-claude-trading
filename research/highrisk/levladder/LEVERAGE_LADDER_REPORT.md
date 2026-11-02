# Leverage ladder on the shipped A1 book — crypto-defi-analyst step

Date 2026-11-02. Engine: `ll_common.Book` re-validated against the shipped backtest (`validation_1x.json`, all pass): 1x arm reproduces 18/18 episodes, 40/40 trades, funding/yr to the cent (2021 −24.76%, 2024 −14.75%), FULL MDD −42.50% and OOS MDD −35.31% exact, FULL CAGR 33.67% vs shipped 33.78% (11bp/yr: mark-vs-trade stamp pricing on re-simulated deadband trims). All numbers from local Binance files; liquidation checked on 5m mark lows with real funding stamps, tier-aware MMR, shipped ±5% deadband mechanics.

## Verdict ladder (for quant-researcher)

| L | verdict | const_kill_episodes | const_FULL_cagr_pct | const_FULL_mdd_pct | naive_Lx_mdd_pct | best_cond_arm | best_cond_mdd_pct | mandate_breach |
|---|---|---|---|---|---|---|---|---|
| 1.5 | PASS-TO-QR | [] | 44.79 | -59.53 | -63.8 | L1.5_rv50 | -49.77 | True |
| 2.0 | PASS-TO-QR | [] | 51.59 | -74.85 | -85.0 | L2.0_rv50 | -62.22 | True |
| 3.0 | PASS-TO-QR | [] | 44.88 | -92.32 | -127.5 | L3.0_rv60_dd20 | -81.46 | True |
| 5.0 | PASS-TO-QR (conditional only) + ECONOMIC-RUIN FLAG | [1] | 1556600.57 | -74.67 | -212.5 | L5.0_rv50 | -97.75 | True |
| 10.0 | KILLED | [1, 3, 4, 5, 6, 7, 8, 10, 11, 12, 17] | 5.370936518800662e+22 | -20.73 | -425.0 | L10.0_rv50 | -73.39 | True |

## Key structural finding: two different kill mechanisms

1. **Entry-anchored geometry (static screen) looks deceptively safe.** Worst adverse mark excursion vs episode-entry fill across all 18 episodes is **18.83%** (ep12, 2024-05-01). Against entry-time LP distances, even 5x (19.68%) breaches **zero** episodes; only 10x (9.64%) breaches, in 6 episodes. The gate+breaker exits crashes within days, so the path is far gentler than mom10x's constant-leverage month-holds (3x died 3/76, 5x 13/76 there).
2. **The dynamic book pyramids.** Holding notional = L×equity with the shipped ±5% deadband forces ADDS on the way up (ratio falls as equity grows), blending EP upward. After the 2020H2 bull, ep1's 5x book had re-anchored near 40k and died in the Jan-11-2021 correction at mark 30,473.55 vs LP 30,506 — **7.5 hours before the breaker's own exit** (00:05 01-12). 10x died the same way in the 2020-08-02 flash dump (day 14 of ep1). Static excursion screens miss this entirely; any leverage backtest must model the deadband adds, not just episode-entry LP distance.

## Episode kill map (standalone episode sims)

| ep | entry_day | L | kill_time | lp_dist_pct_at_entry | tier_at_entry |
|---|---|---|---|---|---|
| 1 | 2020-07-19 | 5.0 | 2021-01-11 16:35:00 | 19.68 | 1 |
| 1 | 2020-07-19 | 10.0 | 2020-08-02 04:40:00 | 9.64 | 1 |
| 3 | 2021-02-23 | 10.0 | 2021-02-23 08:10:00 | 9.55 | 2 |
| 4 | 2021-03-10 | 10.0 | 2021-04-18 03:30:00 | 9.55 | 2 |
| 5 | 2021-05-11 | 10.0 | 2021-05-12 22:35:00 | 9.55 | 2 |
| 6 | 2021-08-10 | 10.0 | 2021-09-07 14:55:00 | 9.55 | 2 |
| 7 | 2021-09-15 | 10.0 | 2021-09-20 12:35:00 | 9.55 | 2 |
| 8 | 2021-10-02 | 10.0 | 2021-12-04 05:00:00 | 9.64 | 1 |
| 10 | 2023-03-24 | 10.0 | 2023-08-17 21:40:00 | 9.55 | 2 |
| 11 | 2023-10-20 | 10.0 | 2024-01-12 22:20:00 | 9.55 | 2 |
| 12 | 2024-03-31 | 10.0 | 2024-04-13 20:05:00 | 9.55 | 2 |
| 17 | 2025-04-23 | 10.0 | 2025-10-10 21:10:00 | 9.55 | 2 |


Min within-episode equity ratio per L (1.0 = never underwater; <0.25 = economic near-ruin):

| ep | entry_day | 1.0 | 1.5 | 2.0 | 3.0 | 5.0 | 10.0 |
|---|---|---|---|---|---|---|---|
| 1 | 2020-07-19 | 0.998 | 0.996 | 0.995 | 0.993 | 0.721 | 0.976 |
| 2 | 2021-02-05 | 0.997 | 0.995 | 0.994 | 0.991 | 0.984 | 0.969 |
| 3 | 2021-02-23 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| 4 | 2021-03-10 | 0.83 | 0.745 | 0.647 | 0.498 | 0.244 | 0.134 |
| 5 | 2021-05-11 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| 6 | 2021-08-10 | 0.958 | 0.936 | 0.915 | 0.861 | 0.567 | 0.462 |
| 7 | 2021-09-15 | 1.0 | 1.0 | 1.0 | 1.0 | 0.998 | 1.0 |
| 8 | 2021-10-02 | 0.903 | 0.844 | 0.774 | 0.576 | 0.244 | 0.036 |
| 9 | 2023-01-14 | 0.994 | 0.98 | 0.959 | 0.877 | 0.668 | 0.15 |
| 10 | 2023-03-24 | 0.876 | 0.817 | 0.746 | 0.606 | 0.357 | 0.041 |
| 11 | 2023-10-20 | 0.998 | 0.998 | 0.997 | 0.995 | 0.992 | 0.985 |
| 12 | 2024-03-31 | 0.828 | 0.749 | 0.673 | 0.505 | 0.238 | 0.368 |
| 13 | 2024-07-15 | 0.994 | 0.982 | 0.981 | 0.958 | 0.858 | 0.486 |
| 14 | 2024-09-27 | 0.972 | 0.958 | 0.944 | 0.915 | 0.858 | 0.68 |
| 15 | 2024-10-15 | 1.0 | 1.0 | 0.999 | 0.999 | 0.998 | 0.06 |
| 16 | 2025-03-20 | 0.96 | 0.94 | 0.92 | 0.881 | 0.804 | 0.592 |
| 17 | 2025-04-23 | 0.998 | 0.997 | 0.996 | 0.994 | 0.952 | 0.504 |
| 18 | 2026-08-21 | 0.999 | 0.998 | 0.998 | 0.997 | 0.965 | 0.487 |

## Conditional rules (rv10<=X at decision close, optional dd-from-episode-peak)

| arm | dead | kill_ep | FULL_cagr_pct | FULL_mdd_pct | FULL_sharpe | OOS_cagr_pct | OOS_mdd_pct | n_trades | fees_total_usdt |
|---|---|---|---|---|---|---|---|---|---|
| strategist_1.5_rv60 | False | nan | 38.38 | -54.7 | 0.876 | 24.83 | -47.31 | 134 | 2220.09 |
| L1.5_rv50 | False | nan | 38.11 | -49.77 | 0.891 | 20.76 | -49.77 | 144 | 2529.12 |
| L1.5_rv50_dd15 | False | nan | 35.01 | -49.91 | 0.854 | 18.44 | -49.91 | 145 | 2333.58 |
| L1.5_rv50_dd20 | False | nan | 37.94 | -49.77 | 0.891 | 20.53 | -49.77 | 143 | 2536.69 |
| L1.5_rv60 | False | nan | 38.38 | -54.7 | 0.876 | 24.83 | -47.31 | 134 | 2220.09 |
| L1.5_rv60_dd15 | False | nan | 33.83 | -55.56 | 0.819 | 21.25 | -47.67 | 144 | 2021.5 |
| L1.5_rv60_dd20 | False | nan | 38.32 | -54.14 | 0.877 | 24.38 | -47.31 | 136 | 2249.96 |
| L1.5_rv70 | False | nan | 41.2 | -54.37 | 0.894 | 25.87 | -51.26 | 131 | 2163.22 |
| L1.5_rv70_dd15 | False | nan | 36.06 | -56.56 | 0.835 | 22.48 | -51.83 | 149 | 2117.28 |
| L1.5_rv70_dd20 | False | nan | 40.79 | -55.24 | 0.892 | 25.86 | -51.27 | 125 | 2125.11 |
| L2.0_rv50 | False | nan | 41.05 | -62.22 | 0.862 | 19.18 | -62.22 | 192 | 5423.58 |
| L2.0_rv50_dd15 | False | nan | 34.41 | -64.37 | 0.791 | 14.19 | -64.37 | 189 | 4452.98 |
| L2.0_rv50_dd20 | False | nan | 40.74 | -62.88 | 0.861 | 18.69 | -62.88 | 191 | 5439.54 |
| L2.0_rv60 | False | nan | 40.81 | -65.88 | 0.843 | 26.6 | -56.83 | 198 | 4521.51 |
| L2.0_rv60_dd15 | False | nan | 32.31 | -67.1 | 0.754 | 19.96 | -57.96 | 199 | 3602.36 |
| L2.0_rv60_dd20 | False | nan | 41.07 | -64.93 | 0.847 | 26.12 | -56.83 | 197 | 4598.96 |
| L2.0_rv70 | False | nan | 45.55 | -67.32 | 0.875 | 29.29 | -62.89 | 208 | 4562.28 |
| L2.0_rv70_dd15 | False | nan | 35.74 | -69.51 | 0.782 | 22.28 | -64.0 | 217 | 4000.18 |
| L2.0_rv70_dd20 | False | nan | 44.87 | -67.52 | 0.871 | 28.74 | -62.89 | 202 | 4509.27 |
| L3.0_rv50 | False | nan | 38.4 | -82.73 | 0.805 | 10.07 | -82.73 | 281 | 13418.29 |
| L3.0_rv50_dd15 | False | nan | 27.31 | -84.27 | 0.705 | 2.21 | -84.27 | 273 | 9244.56 |
| L3.0_rv50_dd20 | False | nan | 38.67 | -83.17 | 0.807 | 9.34 | -83.17 | 279 | 13778.56 |
| L3.0_rv60 | False | nan | 32.87 | -83.1 | 0.775 | 20.64 | -76.08 | 332 | 9404.74 |
| L3.0_rv60_dd15 | False | nan | 18.75 | -86.38 | 0.65 | 9.26 | -77.75 | 327 | 5921.84 |
| L3.0_rv60_dd20 | False | nan | 34.31 | -81.46 | 0.785 | 20.02 | -76.08 | 327 | 9843.97 |
| L3.0_rv70 | False | nan | 40.18 | -84.75 | 0.842 | 25.08 | -81.19 | 366 | 10973.96 |
| L3.0_rv70_dd15 | False | nan | 23.49 | -89.19 | 0.713 | 12.93 | -82.0 | 365 | 7561.91 |
| L3.0_rv70_dd20 | False | nan | 39.4 | -84.54 | 0.834 | 24.22 | -81.19 | 358 | 10763.33 |
| L5.0_rv50 | False | nan | 6.2 | -97.75 | 0.746 | -22.32 | -97.75 | 432 | 23632.01 |
| L5.0_rv60 | False | nan | -10.81 | -98.7 | 0.726 | -11.43 | -95.86 | 529 | 13074.09 |
| L10.0_rv50 | True | 1.0 | 15420.06 | -73.39 | 3.026 | nan | nan | 26 | 1054.15 |
| L10.0_rv60 | True | 1.0 | 103.77 | -76.21 | 2.178 | nan | nan | 32 | 1225.22 |


Gate-on days with rv10≤60%: **71.2%** (≤50%: 57.4%, ≤70%: 81.3%). Kill forensics by type (verified rv10 paths in `verdict.json`): (i) **pyramid-then-correction** — the 5x ep1 kill (2021-01-11): rv10 had been >60% for a week, so an rv10≤60% rule is flat-to-1x 8.5 days before the kill bar and dodges the liquidation (but the toggle whipsaw still costs −98.7% MDD at 5x); (ii) **calm-to-crash gap days** — 2020-09-03 (rv10 0.32–0.45 all week), 2025-10-10 (0.24–0.35): invisible to any vol-state rule, undodgeable; (iii) **threshold knife-edge** — eps 11/12 at 10x: rv10 straddles 0.60 (0.51–0.63), the rule toggles out and back in days before the kill bar (re-leveraged 00:05 04-11 at rv10 0.599, killed 04-13 20:05) — survival is threshold luck, not skill. dd-from-peak overlays (15%/20%) consistently *reduce* CAGR via whipsaw without improving MDD — dead end.

## Drag scaling (per unit of margin equity)

| L | lp_dist_pct | fund_inmarket_2021_pct | fund_inmarket_2024_pct | fund_inmarket_2026_pct | fund_inmarket_OOS_pct | taker_per_roundtrip_pct | fee_drag_ann_pct_sim | breakeven_g_inmarket_FULL_pct | gross_g_FULL_pct | net_uplift_per_unit_FULL_pct |
|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 100.0 | 35.0 | 14.1 | 5.8 | 9.3 | 0.1 | 1.19 | 15.2 | 82.8 | 0.0 |
| 1.5 | 66.53 | 52.5 | 21.1 | 8.7 | 14.0 | 0.15 | 3.11 | 15.2 | 82.8 | 33.8 |
| 2.0 | 49.8 | 70.0 | 28.2 | 11.6 | 18.7 | 0.2 | 7.35 | 15.2 | 82.8 | 67.6 |
| 3.0 | 33.07 | 105.0 | 42.3 | 17.4 | 28.0 | 0.3 | 21.78 | 15.2 | 82.8 | 135.2 |
| 5.0 | 19.68 | 175.0 | 70.5 | 28.9 | 46.7 | 0.5 | 9.55 | 15.2 | 82.8 | 270.5 |
| 10.0 | 9.64 | 350.0 | 140.9 | 57.9 | 93.4 | 1.0 | 0.62 | 15.2 | 82.8 | 608.5 |


In-market funding at 1x per notional-year: 2021 **35.0%**, 2024 14.1%, 2026 5.8%, OOS-avg 9.3% — at L it is L×. Break-even gross held return FULL ≈ 15.2%/yr vs realized 82.8%/yr: per-unit economics justify leverage in-sample, but realized compounding caps at 2x (3x CAGR 44.9% < 2x 51.6%) because fee churn (3x: 393 trades, 21.8%/yr fee drag) and deleverage-releverage convexity eat the theoretical uplift.

## Mandate check (user MDD tolerance 40–50%)

- 1x shipped: −42.5% realized (inside), bootstrap median −47.4%, worst −74.6%.
- **1.5x**: const −59.5%, strategist rv60 −54.7%, best variant (rv50) −49.8% — only inside the band by post-hoc variant picking (9-variant scan = selection bias).
- **2x**: −74.9% const, −62.2% best conditional. Far outside.
- **3x**: −92.3% const. Near-ruin without liquidation.
- Bootstrap envelope at 1x already reaches −74.6%; any L>1 puts total ruin inside the 95% envelope. The mandate as stated (40–50%) admits **no leverage >1x** without either raising tolerance or accepting a post-hoc-picked condition.

## Handoff to quant-researcher

Arms worth a real backtest (in priority order): (1) **constant 1.5x** — cleanest, survives everything, CAGR 44.8% vs 33.7%, MDD −59.5% is the blocker; (2) **strategist's spec-§8 arm** (1.5x iff rv10≤60%) — CAGR 38.4%, MDD −54.7%; (3) **constant 2x** — geometry survives, CAGR 51.6%, MDD −74.9% needs an explicit tolerance raise. Do NOT backtest 5x/10x as constants (liquidated on the actual path). Backtest engine MUST implement the deadband adds (EP blending) — entry-anchored LP checks are non-conservative by up to 3x on this path (5x static-safe, 5x dynamic-dead). Bootstrap any candidate: 1x worst-resample −74.6% scales ~L×.

## Files
- `episodes_excursions.csv` (task 1), `ladder_static.csv` / `ladder_dynamic.csv` / `ladder_by_episode.csv` (task 2), `conditional_rules.csv` / `conditional_stats.json` (task 3), `drag_scaling.csv` / `drag_regimes.json` (task 4), `verdict.json` (task 5), `book_*.json` per-arm equity + episode detail, `ll_common.py` engine, `validation_1x.json` engine parity.
