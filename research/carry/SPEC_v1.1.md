# BTCUSDT Funding-Rate Carry Strategy — Formal Specification

**Version:** 1.1 (supersedes v1.0 — see §14 Amendment Record)
**Status:** APPROVED WITH CONDITIONS — deployment blocked until §12 conditions are satisfied in writing
**Date:** 2026-11-02
**Instrument:** Binance spot BTCUSDT (long leg) + Binance USDⓈ-M BTCUSDT perpetual (short leg)
**Evidence base:** 6.84-year mechanical backtest on exchange-verified data (2019-12-31 → 2026-10-31), 28/28 unit tests, risk-gate reproduction 27/27 figures exact. All artifacts in `research/carry/` (see Appendix A).

---

## 1. Economic Rationale

Binance perpetual swaps settle a funding payment every 8 hours (00:00 / 08:00 / 16:00 UTC) between longs and shorts. Because leveraged long demand structurally exceeds short supply in crypto, **longs paid shorts in 85.8% of all 7,830 historical funding periods** (2019-09 → 2026-11), mean +0.01046%/8h.

This strategy holds a delta-neutral position — long spot, short perp, equal notional — so price P&L cancels and the residual return stream is the funding payment. **The strategy makes no price prediction, uses no indicators, and takes no directional view.** Its edge is a structural payment, not forecasting skill.

Key regime fact (statistically confirmed, t=4.5): Binance's 2025-09-18 funding-formula change cut the mean payment 62%. Full-history mean 11.46%/yr is **not** the forward expectation; see §11 for honest yield figures.

## 2. Instruments and Venue

| Item | Long leg | Short leg |
|---|---|---|
| Venue / market | Binance spot BTCUSDT | Binance USDⓈ-M perpetual BTCUSDT |
| Margin mode | n/a | **Isolated**, one-way |
| Leverage | n/a | 2x (margin = 0.5 × notional) |
| Fee (taker) | 0.10% | 0.05% |
| Size step | 0.001 BTC (both legs; spot/perp step differences rounded conservatively) | 0.001 BTC |
| Min notional | per exchange rules | 50 USDT |

Exchange concentration (both legs on Binance) is a known, accepted, capped risk — see §9.

## 3. Frozen Parameters

| Parameter | Value | Origin |
|---|---|---|
| Notional ratio | 1:1 (spot qty = perp qty, always) | design |
| Capital model | N = C / 1.6 (N = deployed notional per leg; C = allocated capital) | margin 0.5N + reserve 0.1N |
| Short-leg margin ratio q | 0.5 (2x) | liq-distance prior |
| Rebalance trigger θ | **20%** (frozen) | a-priori liq buffer, NOT optimized; θ=25% verified fragile (min liq distance 3.0%) |
| Trigger scan | every completed 4h bar, on 4h **high** | backtest-robust |
| Rebalance size Δ | floor(Q/6, 0.001) | exact solution of margin-restore equation at trigger |
| Funding timestamps | 00/08/16 UTC, exchange values floored to the hour | verified across 7,830 events |
| Sweep rule (v1.1) | w = max(0, M − M_floor) | §7.3 |
| Circuit breaker | rolling-90d annualized carry < 0 for 60 consecutive days → review/de-risk | quant-researcher |
| Economic floor | rolling-90d annualized **net** carry < +1.5%/yr for 60 days → wind down | risk-manager (added; the carry-positive breaker cannot catch formula compression) |

**Prohibited without full pipeline re-validation:** changing θ or any frozen parameter; funding-based entry/exit conditioning (tested as H2/H3 and rejected — all variants significantly destroy value, IS and OOS); re-compounding harvested carry into the position (v1.1 deliberately does not compound; a compounding variant is a future enhancement requiring its own IS/OOS study); leverage above 2x on the short leg; naked (unhedged) short.

## 4. Sizing

- Notional per leg: N = C/1.6. Quantity: Q = floor(N / P_entry, 0.001) BTC; rounding residual (≤ 1%) goes to reserve, uninvested.
- **Minimum viable size:** 0.05 BTC notional per leg (below this, 0.001-step rounding residuals exceed 1% and Δ=Q/6 rounding error becomes material). At BTC $75k–$115k this is ≈ $6,000–$9,200 capital.
- **Position limit (risk-gate binding):** C ≤ 10% of portfolio NAV; **5% for the first 6 months** of live operation.
- Kelly sizing is explicitly rejected: the binding risks are jump/counterparty, not carry-stream variance.

## 5. Entry Procedure

1. One-shot entry (no scaling — proportional fees make scaling costless-neutral but operationally weaker). Clock rule only: complete entry 30–60 min before a funding timestamp so the position begins accruing immediately. No funding-level conditioning (prohibited, §3).
2. **Spot leg first** (naked long has no liquidation property), then perp short. Naked-leg window ≤ 60 seconds; on failure of the second leg, fully roll back the first.
3. Set anchor P0 = perp execution price. Set margin floor M_floor = 0.5 × N (post-fee wallet).

## 6. Funding Accrual

- At each 00/08/16 UTC timestamp, if the short position is open across the timestamp: credit Q × mark_price × funding_rate when rate > 0; debit when rate < 0 (signs per exchange convention).
- Funding timestamps in historical data are floored to the hour (millisecond jitter exists in exchange records).
- Negative-funding stretches are **held through**, never exited (historical deepest: −103.7bp over 8 days, Mar 2020; median stretch 1 period).

## 7. Rebalancing Protocol (the strategy's only moving part)

Delta never drifts (both legs hold identical BTC quantity), so rebalancing is purely margin management.

### 7.1 Upside trigger (margin protection)
- Scan: each completed 4h bar, if `high ≥ 1.20 × P0` → trigger. Execution at that bar's close (backtest assumes the slowest realistic fill; live SLA ≤ 15 min, §10).
- Action: reduce **both legs** by Δ = floor(Q/6, 0.001) BTC (buy back perp short Δ; sell spot Δ). Spot proceeds first refuel the perp wallet to restore q = 0.5; if insufficient, top up from reserve (reserve = 0.1N + swept carry). Log any unmet top-up (backtest: 10 top-ups, $1,110 total, unmet = 0).
- Reset anchor P0 = execution price; re-anchor M_floor to the restored wallet.
- Exact-solution note: Δ* = (0.5·Q·P1 − E)/(1.5·P1) = Q/6 exactly at the +20% trigger point.

### 7.2 Downside / profit side (v1.1 sweep rule — CRITICAL, see §14)
As price falls, the short leg profits and margin ratio rises above 0.5. **Do not increase the position** (no compounding). Sweep only:
```
w = max(0, M − M_floor)      # M = current isolated wallet
```
i.e., sweep **collected funding inflows above the anchored margin floor only**. Principal margin and unrealized P&L are never swept.

### 7.3 Why v1.1 wording is binding
v1.0 read "sweep excess margin back to q=0.5." On 2020-04-02 that rule, simulated faithfully, drained the wallet during the COVID crash and let the liquidation price chase the price down — the short leg was liquidated in the V-shaped rebound (RUN A evidence). v1.1's floor-locked sweep makes the liquidation price monotonically non-decreasing between rebalances (verified: max non-rebalance LP drift $109.61 on a five-figure LP). **The v1.0 sweep semantics are permanently banned.**

## 8. Exit and Wind-Down

1. Trigger conditions: economic floor (§3), circuit breaker review, structural event (funding formula / contract spec announcement → 72h impact review with pre-registered go/no-go), compliance event, or manual decision.
2. Sequence: **close perp leg first, then sell spot** (minimizes the naked window; spot cannot be liquidated).
3. Costs on exit: perp taker 0.05% + spot taker 0.10%.

## 9. Risk Controls (risk-gate binding conditions)

| # | Control | Threshold / action |
|---|---|---|
| 1 | Position cap | ≤10% NAV (5% first 6 months) |
| 2 | De-risk ladder | strategy drawdown > 5% → halve; > 8% → stop and review |
| 3 | Kill switch | liquidation distance < 10% → alert; **< 5% → auto cut risk 50%, no human decision needed** |
| 4 | Margin tier check | monthly re-verify position stays within MMR ≤ 0.5% tier; recompute LP with current tier table |
| 5 | Economic floor | §3; wind down on breach |
| 6 | Parameter freeze | any change → full pipeline re-validation (quant → backtest → risk) |
| 7 | Profit custody | sweep accumulated carry off-exchange monthly; on-exchange reserve capped at 0.2N |

**The three real tails** (market risk is not one: backtest MDD −0.69%, worst day −0.29%):
- **ADL** — exchange auto-deleveraging can force-close the profitable short leg in a cascade crash, leaving naked spot. Worst case ≈ −18% of capital without playbook; −2–4% with playbook (re-hedge within 1h). Playbook + quarterly drill are mandatory.
- **Exchange counterparty** — both legs on one venue; FTX-type failure can lose all deployed capital. Mitigated only by the position cap and profit sweeps.
- **Funding-formula change** — happened once (−62%); a repeat compresses yield to ~1.2%/yr, which the economic floor (not the circuit breaker) is designed to catch.

## 10. Monitoring & Operations

Daily dashboard (with alert thresholds):
1. Liquidation distance (alert < 10%, kill < 5%)
2. Rolling-90d annualized net carry (economic floor 1.5%/yr; breaker 0)
3. Margin ratio q on short leg (target 0.5; investigate < 0.45)
4. Anchor distance: current price vs 1.2×P0 (pre-alert at +18%)
5. Negative-funding streak length (context only; no action)
6. Reserve balance vs 0.2N cap
7. Exchange announcement feed (funding formula, margin tiers, ADL rules — highest priority)

Operational requirements: rebalance execution SLA ≤ 15 minutes from trigger (backtest survived 4h; SLA is margin, not hope); ADL response script tested quarterly; kill-switch test record before go-live.

## 11. Performance Evidence & Honest Expectations

Backtest (2019-12-31 → 2026-10-31, $10,000 capital, N=$6,250, real spot+perp+funding data, all fees):

| Metric | Value |
|---|---|
| Net return | +74.05% on N (+46.28% on C) over 6.84 yrs |
| Annualized | 10.83% on N · 6.77% on C |
| Max drawdown | −0.69% |
| Sharpe (daily) | 8.25 (misleading headline — returns are near-deterministic; judge by tails, §9) |
| Significance | NW t = 8.63 |
| Rebalances | 15, total cost $28.42 |
| Funding collected | $4,693 net |
| Liquidation events | **0** (min distance +20.9%, 2020-12-26) |
| Post-2025-09-18 run-rate | **2.68%/yr on N** (1.68% on C) |

**Forward 12-month expectation (use these, never the full-history number):** base case ~3.1%/yr on N (CI 2.0–4.2, ~60% weight); mixed regime 6.5% (~30%); bull return ~16% (~10%). Probability-weighted ≈ **5.4%/yr on N ≈ 3.4%/yr on C**. Per-year backtest yields ranged 2.0% (2022 bear) to 31.4% (2021 bull).

## 12. Compliance Prerequisites (CONDITIONAL PASS — all must be satisfied in writing before deployment)

- **CP1** Jurisdiction eligibility declaration + legal opinion. Strategy is **prohibited** for: US persons; mainland China residents; retail participants in UK/EU/HK/Singapore; Japan residents via offshore venues; anyone accessing via VPN or false representation; regulated entities managing client money on an offshore venue.
- **CP2** Written confirmation the trading entity is proprietary/self-funded.
- **CP3** Core documents: risk disclosure, best-execution policy, algorithm description, kill-switch test record, ADL procedure.
- **CP4** Self-trade prevention enabled; position hard limits configured; monthly MMR tier re-check.
- **CP5** AML/tax readiness: CARF/DAC8 reporting (began 2026); local advice on funding income vs leg P&L tax treatment and the spot/perp leg mismatch.

## 13. Known Limitations

1. Yield is regime-dependent and compressing (§1); the strategy can become not-worth-running while still positive — hence the economic floor, not a stop-loss.
2. No compounding by design; bull-market position size decays geometrically ((5/6)^k per rebalance).
3. Carry correlates with BTC at monthly frequency (+0.30) — it is not a perfect hedge against crypto portfolio drawdowns.
4. ADL and exchange-failure tails are not backtest-modelable; they are bounded by operational controls, not by the backtest.
5. Capacity is endogenously limited (funding is a zero-sum transfer); desk-level sizing guidance: keep position small relative to perp open interest.

## 14. Amendment Record

| Version | Change | Reason |
|---|---|---|
| v1.0 (2026-11-02) | Initial frozen spec (algo-strategist) | — |
| **v1.1 (2026-11-02)** | Sweep semantics rewritten (§7.2): floor-locked sweep `w = max(0, M − M_floor)` replaces "restore q=0.5 by sweeping"; M_floor re-anchored at entry and each rebalance | v1.0 rule self-liquidated the short leg on 2020-04-02 in faithful simulation (RUN A). Fix preserves the no-compounding intent, is one-directional (stricter margin), verified by 28 unit tests + full re-backtest + independent risk-gate reproduction |

---

## Appendix A — Artifact Inventory & Reproduction

All under `research/carry/`:

| File | Role |
|---|---|
| `SPEC_v1.1.md` | this document |
| `carry_mechanism_analysis.py` | funding regime / liq-distance / construction analysis (crypto-defi-analyst) |
| `qr_carry_feasibility.py` + `_log.txt` | viability tests: significance, H1/H2/H3 rejection, forward scenarios (quant-researcher) |
| `carry_backtest.py` | backtest engine (event-sourced state machine) |
| `carry_backtest_tests.py` + `carry_bt_tests_log.txt` | 28 unit tests |
| `carry_backtest_run.py` | base + 5 robustness configs runner |
| `carry_bt_results.json` | all run results |
| `carry_bt_equity_base.csv` | daily equity, base config |
| `carry_bt_rebalances.csv` | 15 rebalance records |
| `carry_bt_run_log.txt` | run log |
| `binance_spot_btcusdt_1h_download.py` + `spot_1h_dl.log` | spot data downloader (sha256-verified) |
| `data/binance_spot_btcusdt_{1h,4h}.csv` | spot leg data (60,641 1h bars) |

Shared data (remain in `research/data/`): perp 5m/4h klines, mark-price 5m, funding history.

Reproduce:
```bash
cd <workspace>
PYTHONPATH=research/.pylibs python3 research/carry/carry_backtest_tests.py   # 28 checks
PYTHONPATH=research/.pylibs python3 research/carry/carry_backtest_run.py     # full rerun, ~2 min
```
Expected: ann 10.825%/N, MDD −0.694%, liq events 0, min liq distance 20.92%, post-break 2.682%/N.

## Appendix B — Approval Trail

| Gate | Verdict | Date |
|---|---|---|
| Signal viability (quant-researcher) | PASS (t=5.65 post-break; Deflated-Sharpe clean) | 2026-11-02 |
| Mechanical backtest (backtesting-engineer) | PASS after v1.1 fix (v1.0 NO-GO documented) | 2026-11-02 |
| Risk gate (risk-manager) | APPROVE with 11 binding conditions (§9–§10) | 2026-11-02 |
| Compliance (regulatory-compliance) | CONDITIONAL PASS, CP1–CP5 (§12) | 2026-11-02 |

**No live orders have been placed. Deployment remains blocked until §9 and §12 conditions are evidenced in writing.**
