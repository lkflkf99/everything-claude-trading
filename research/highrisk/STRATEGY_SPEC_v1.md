# STRATEGY SPEC v1.0 — TG1x-hyst2 + VB(10,100,5)

**Status:** FROZEN for backtesting. **Author:** algo-strategist. **Date:** 2026-11-02.
**Lineage:** signal = `TG1x-hyst2` exactly as frozen by quant-researcher (`research/highrisk/qr_final_spec.json`). This spec adds a drawdown-deleverage overlay, execution, sizing, and risk controls. **The signal is not modified.**

Diagnostics backing every design choice: `algo_dd_diag.py` / `algo_dd_diag.json` (drawdown episodes, vol-breaker traces, funding stamp economics, liquidity) and `algo_ts_trace.py` / `algo_ts_episodes.csv` (trailing-stop traces). These scripts compute trigger traces and market statistics only — no overlay PnL was simulated by the algo-strategist; all performance claims below are expectations to be verified by the backtesting-engineer.

---

## 1. Instrument, venue, account

- **Instrument:** Binance USDT-margined BTCUSDT perpetual. Step 0.001 BTC. Min notional 50 USDT.
- **Account:** dedicated exchange **sub-account** (never shared with the approved funding-carry strategy or any other book — prevents position netting and keeps margin accounting separable).
- **Margin mode:** **isolated**, leverage setting 1×. Collateral: USDT only.
- **Reference capital:** 10,000 USDT. Sizing rules below are stated per unit of equity and scale linearly.
- **Why isolated 1×:** at 1× the liquidation price sits ≈ −99% below entry; the position is structurally unliquidatable, which makes the strategy **exchange-outage tolerant by construction** (see §8). No margin calls in any scenario short of BTC → 0.

## 2. Data definitions (all timestamps UTC)

- **Decision bar for date D:** the daily close `C(D)` printed at **00:00 UTC on date D** (the day boundary; Binance daily kline close of date D−1).
- `SMA200(D) = mean(C(D−199) … C(D))` — 200 daily closes, matching QR.
- Daily simple return `r(D) = C(D)/C(D−1) − 1`.
- `rv10(D) = std(r(D−9) … r(D)) × √365` (sample std, ddof=1), annualized. Needs 10 returns → defined from the 11th close onward.
- Funding stamps: 00:00, 08:00, 16:00 UTC daily. Any position open at a stamp pays/receives `funding_rate × notional` (long pays when rate > 0).

## 3. Signal (QR-frozen, restated verbatim)

```
state(D): 0→1 when C(D) > 1.02 × SMA200(D)
          1→0 when C(D) < 0.98 × SMA200(D)
          else hold previous state
```
Before SMA200 is defined (first 200 closes), state = 0.

## 4. Drawdown-deleverage overlay — PRIMARY: vol circuit breaker VB(10,100,5)

Binary circuit breaker on realized vol. Deterministic state machine given the daily series.

```
vb_state ∈ {ON, OFF};  below_count ∈ ℕ;  init: vb_state = ON, below_count = 0
Computed at each decision bar D:
  if rv10(D) undefined → no transition (vb_state unchanged)
  if vb_state = ON  and rv10(D) > 1.00  → vb_state = OFF, below_count = 0
  if vb_state = OFF:
      if rv10(D) ≤ 1.00 → below_count += 1; if below_count = 5 → vb_state = ON, below_count = 0
      else               → below_count = 0
overlay multiplier m(D) = 1 if vb_state = ON else 0
```

**Combined position rule:** `w(D) = state(D) × m(D)`, applied at the 00:05 UTC execution on date D. w ∈ {0,1}; the overlay can only reduce exposure, never increase it.

**Why this mechanism (paper evidence, not backtest):**
- The −56.5% full-sample MDD decomposes into (i) the slow-exit ride (equity −45.1% by the 2021-05-19 gate exit) and (ii) the May–Dec 2021 whipsaw cluster (−20.9% compounded on the reduced equity).
- All three deep drawdown episodes in sample (−27.4% Jan-2021, −56.5% Mar-2021→2023, −33.5% 2024, −29.0% 2024-25) had rv10 cross 100% **before** the trough (`algo_dd_episodes.csv`). The only two uncovered episodes were shallow (−18.7%, −10.9%) and recovered in weeks.
- May 2021 specifically: rv10 crossed 100% at close 2021-05-12 (108%), strategy dd at the time −25.4%, price 49.6k — **7 days before** the gate exit at 36.7k (dd −45.1%). The 2021-05-20→21 re-entry whipsaw (−8.1%) is fully blocked (breaker OFF). The Aug–Dec 2021 chop is **not** blocked (rv10 69–89% < 100%) — accepted: projected 2021 trough ≈ 1 − 0.75×(1−0.209) ≈ **−40%** vs −56.5% baseline, inside the user's 40–50% tolerance. Backtester verifies.
- **Flat sensitivity surface:** rv10 peaked at 138–159% in the covered crises, so every threshold in X ∈ [80,120] fires within ~1 day of the same date. Contrast with the trailing stop's knife-edge (below). Sensitivity counts (episodes / days OFF): X80: 30/472, X90: 21/313, **X100: 17/233**, X110: 11/140, X120: 11/109 (`algo_dd_diag.json`).
- Cost: ~1.0 extra round trip/yr ≈ **10bp/yr** at 5bp/side; 5.8% of gate-on days blocked (insurance time-cost). Trivial vs the ~10%/yr full-sample funding drag it partially sidesteps.
- **Not vol targeting:** QR killed *continuous* vol targeting (w = 0.50/rv30) as a Sharpe wash. VB is a binary catastrophic-regime filter: the trigger condition (rv10 > 100%) is present on only 3.2% of gate-on days, and total blocked exposure is 5.8% of gate-on days including the re-arm lag. Objective is tail control, not return enhancement. Different mechanism, different objective.

**Why threshold 100%:** round number at the 95th percentile of all-days rv10 (p95 = 103%); a priori definition of "extreme vol regime." Not optimized — but chosen *knowing* the 2021 crashes exceeded it → **selection-bias flag, see §11.**

## 5. Overlay — FALLBACK (horse-race arm only, not in v1.0 primary): trailing stop TS(30)

```
while state = 1: cycle_peak = max(close) since the most recent 0→1 gate transition
fire when C(D) < (1 − 0.30) × cycle_peak → m_TS = 0 from next execution
re-arm: only at the next 0→1 gate transition (cycle_peak resets)
```

Trace evidence (`algo_ts_episodes.csv`): fires 2021-05-17 at 43.6k (gate exit was 05-19 at 36.7k — saves ~17pp of equity) and 2021-12-10; only 21 blocked gate-on days. **Documented fragility:** τ=25% fires 2021-01-27 at 30.4k in a normal bull correction and locks out until 2021-08-09, missing the entire 30k→63k leg; τ=30% escapes by 4.8pp. This knife-edge is why TS is the fallback and VB (flat surface) is primary. If raced and selected, τ=30% adds **one** parameter.

## 6. Rejected overlay candidates (paper comparison)

| Candidate | Params | Verdict | Reason |
|---|---|---|---|
| (a) Equity-DD ladder (−30% → flat, re-arm at gate re-fire) | 1–2 | **REJECTED** | Degenerate in trace: 8 breaches, instant re-breach after re-arm (equity still >30% below a peak set in a prior regime), multi-year lockouts (2021-10-02 → 2023-01-13). Fixing it needs a decaying peak window + re-entry band = param bloat and more selection risk. |
| (b) Trailing stop from cycle peak | 1 | FALLBACK (arm A2) | See §5: works at τ=30, knife-edge vs τ=25. |
| (c) 50d-SMA secondary gate | 2–3 | **REJECTED a priori** | A second timing signal = re-opening signal research (out of mandate); needs its own hysteresis to control whipsaw (2 params) plus a coordination rule with the 200d (3rd param) — over budget; whipsaw cost in chop unquantified. |
| (d) Realized-vol circuit breaker | 2 | **PRIMARY** | See §4. |

## 7. Execution design

- **Decision + execution time:** compute all state at the 00:00 UTC decision bar; execute at **00:05:00 UTC** (T+5 min). Rationale:
  1. *Determinism:* the 00:00 close print is final; no trading on a forming bar.
  2. *Unambiguous funding-stamp treatment (NOT a funding dodge):* entering at 00:05 skips the entry-day 00:00 stamp, but the exit-day 00:00 stamp is still paid (position open at 00:00 on exit day — unavoidable, the exit decision needs the 00:00 close). The two effects offset: verified against QR's daily-sum accounting over all 26 sample round trips, net difference **−0.3bp total (≈0bp/yr)**. Funding timing is *not* worth pursuing economically (consistent with QR's dead funding-contrarian overlay); the stamp-exact rule exists for accounting precision, not alpha.
  3. Avoids trading into the funding-print microstructure noise at exactly 00:00.
- **Order type:** single **taker market order** for the full delta. Justification (cost math): 10k USDT = 0.03% of the median 00:05-bar notional ($30.0M), 0.21% of the p5 bar ($4.9M), 2.2% of the worst bar ever ($457k) → expected impact ≪ 1bp. No TWAP, no clip limit — a 1-hour TWAP adds fill uncertainty for sub-bp savings. **Max clip = full order.**
- **Maker-vs-taker:** taker at 5bp is the charged assumption (QR-parity). A resting maker order at the close is self-referential (the limit price needs the close that the order would influence) and introduces non-deterministic fills — rejected. Gate round trips average 3.8/yr (cost drag 0.38%/yr full sample); worst year 2021 ≈ 9 round trips ≈ 90bp — acceptable.
- **Drift deadband:** if `w = 1` and `|position_notional/equity − 1| ≤ 0.05`, skip the rebalance trade. Primary cause of drift is funding bleed (notional doesn't pay funding, equity does; creep up to ~30%/yr in 2021-like regimes) — the deadband caps effective leverage at 1.05× with ~2 small trades/yr instead of daily dust trades. On breach, rebalance back to exactly 1.00×.
- **Slippage assumption for backtest:** 5bp taker per side on traded notional, QR-parity. Real impact at 10k is sub-bp; 5bp is conservative.

## 8. Position sizing and capital

- **Equity** `E` = sub-account USDT wallet balance + unrealized PnL (marked at execution time).
- **Target notional** `N* = w × E`. **Target quantity** `q* = floor(N*/mark / 0.001) × 0.001` (round DOWN — never exceed 1×).
- If `N* < 50 USDT` → stand down (dust account; irrelevant at 10k reference, stated for completeness).
- **Idle capital (state = 0 or m = 0, ≈45% of days OOS): hold plain USDT in the strategy sub-account in v1.0.** Deliberately *not* parked in the approved funding-carry strategy: (i) carry is a separately approved book with its own risk accounting — commingling breaks it; (ii) carry's short-perp leg and this strategy's long must never share margin (separate sub-accounts are required anyway); (iii) expected value ≈ 0.45 × 3–5% ≈ +1.4–2.3%/yr does not justify the coupling and the twice-per-cycle transfer operations in v1.0. **v1.1 option (documented, NOT active):** on gate 1→0, transfer equity to the carry sub-account after 24h; on gate 0→1, recall at the next execution (carry unwinds per its own spec). Requires risk-manager sign-off.
- **Leverage extension (NOT in v1.0; candidate arm for risk-manager only):** `L = 1.5×` iff `state=1 AND vb_state=ON AND rv10 ≤ 0.60`; else 1×. Hard cap 1.5×, isolated, entry-time check that liquidation distance ≥ 60%. Changes liquidation math (1.5× isolated liq ≈ −63% adverse) and therefore weakens the outage-tolerance argument — needs its own backtest arm and explicit risk-manager approval. **v1.0 ships at 1×.**

## 9. Funding accounting (backtest + live)

- Position pays/receives every stamp at which it is open. With 00:05 execution: entry day → pays 08:00 and 16:00 stamps (skips 00:00); full days held → all 3; exit day → pays the 00:00 stamp only.
- Backtest runs **two accountings**: (i) QR-parity (`w_held × fund_sum` daily, exactly as `qr_final_daily.csv`) for comparability with QR numbers; (ii) **stamp-exact** from `perp_funding.csv` for the honest forward estimate. Verified equivalence: over the 26 sample round trips the two differ by **−0.3bp total (≈0bp/yr)** — QR's daily sum overcharges the pre-entry 00:00 stamp on entry day and undercharges the 00:00 stamp on the day after the exit signal; the effects offset. Report both; **a difference > 10bp/yr indicates a boundary bug — stop and investigate.**
- Funding regime risk (QR): in-market drag 16.9%/yr full-sample average, 29.5%/yr in 2021, ~9.5%/yr OOS. If funding flips persistently negative while gated ON, drag becomes income. No rule exploits this (funding-contrarian overlay is DEAD per QR) — monitoring only.

## 10. Risk controls (execution level)

- **No market-move daily-loss stop.** At 1×, daily PnL = BTC daily return; −10% days occur several times per year and recover; a daily stop would duplicate the overlay's job and whipsaw. Tail control = VB overlay (§4) + gate. Honest worst-case disclosure for risk-manager: baseline (A0) worst held day **−14.4% close-to-close** (2021-05-19). Under A1 the position is flat that day (breaker fired at the 05-12 close, flat from 00:05 05-13) — but A1 still eats the full **−12.5%** trigger day itself (2021-05-12), since the breaker only acts at the next execution; A1's worst held day in-sample ≈ −12.5%. The unconditional BTC worst day is **−40.0%** (2020-03-12, strategy was flat) — that is the honest tail for any 1× long exposure, and no daily-close overlay can react faster than the print.
- **Kill switch (flatten to 0, halt, human alert) on execution-integrity failures only:**
  1. PnL-attribution mismatch: |realized daily PnL − (notional×r − funding − fees)| > 1% of equity.
  2. Position mismatch persists > 15 min after a rebalance (partial fills/rejects) after 6 retries × 5 min.
  3. Exchange margin/ADL warning on the sub-account (structurally near-impossible at 1×; cheap to check).
  4. Decision-bar sanity failure: |C(D)/C(D−1) − 1| > 20% not corroborated by the 5m mark series → suspect bad print → skip the rebalance, alert. (The gate hinges on one print; this guards the signal input, not the PnL.)
- **Exchange outage / API failure in the rebalance window:** retry every 5 min × 6; if still down, alert human and leave the position as-is — safe at 1× isolated (no liquidation path). If a gate/overlay flip is missed by > 24h, execute at first available price with a market order (the signal is slow; a day of delay is noise, not a decision input).
- **Weekend / holiday / low-liquidity:** no special handling. 24/7 market; order size is dust in all observed liquidity regimes (worst 00:05 bar ever $457k vs $10k order).
- **Cooldowns:** after VB fires, re-entry is mechanically delayed by the k=5 below-threshold days (built into the overlay — no separate cooldown needed). After a kill-switch halt: **manual restart only** (human reviews cause; not a mechanical timer).

## 11. Frozen parameters and selection-bias ledger

| # | Parameter | Value | Chosen by | Selection-bias flag |
|---|---|---|---|---|
| 1 | SMA window | 200 d | QR (frozen) | Yes — QR robustness-checked vs neighbors (`qr_gate_robustness.csv`) |
| 2 | Hysteresis band | 2% | QR (frozen) | Yes — QR picked hyst2 post-hoc (`qr_hysteresis_verdict.json`) |
| 3 | Vol window | 10 d | algo-strategist | Mild — task-specified candidate; no alternative tested |
| 4 | VB threshold X | 100% ann. | algo-strategist | **Yes** — justified a priori as ≈p95 of all-days rv10 (103%), but chosen knowing 2021 crises exceeded it; mitigated by flat 80–120 sensitivity surface |
| 5 | VB re-arm persistence k | 5 d | algo-strategist | Mild — round number, untuned; backtester shows k ∈ {3,5,10} |
| 6 | Fallback trail τ (arm A2 only) | 30% | algo-strategist | **Strong** — documented knife-edge: τ=25 catastrophic, τ=30 good (4.8pp gap to the Jan-2021 correction depth) |

Non-signal execution constants (conventions, not tuned): taker 5bp, execution T+5 min, drift deadband ±5% (chosen ≈ 2× typical daily |r| to filter noise trades; untuned), reference capital 10,000 USDT.

**Total tuned/frozen parameters in v1.0 primary: 5 (2 QR + 3 new ≤ the ≤6 budget; fallback arm adds 1).**

## 12. Pseudocode event loop

```
# ---- persistent state ----
gate_state ∈ {0,1} (init 0); vb_state ∈ {ON,OFF} (init ON); below_count = 0
closes = ring buffer of daily closes (≥200)

# ---- daily job, 00:05 UTC (after 00:00 close print AND 00:00 funding stamp) ----
def daily_job(D):
    C = daily_close_at_0000UTC(D)                 # decision bar
    if sanity_fail(C): alert(); return            # §10.4: skip rebalance on bad print
    closes.push(C)
    sma200 = mean(closes[-200:]) if len(closes)>=200 else NaN
    rv10 = std(returns(closes[-11:]), ddof=1)*sqrt(365) if len(closes)>=11 else NaN

    # signal (QR-frozen)
    if !isnan(sma200):
        if gate_state==0 and C > 1.02*sma200: gate_state = 1
        elif gate_state==1 and C < 0.98*sma200: gate_state = 0

    # VB overlay
    if !isnan(rv10):
        if vb_state==ON and rv10 > 1.00: vb_state = OFF; below_count = 0
        elif vb_state==OFF:
            if rv10 <= 1.00:
                below_count += 1
                if below_count == 5: vb_state = ON; below_count = 0
            else: below_count = 0

    w = gate_state * (1 if vb_state==ON else 0)

    E = account_equity()                          # wallet + uPnL
    N_target = w * E
    q_target = floor(N_target/mark_price()/0.001)*0.001
    if N_target < 50: q_target = 0                # dust stand-down
    if w==1 and abs(position_notional()/E - 1) <= 0.05:
        q_target = q_current                      # drift deadband: no trade
    delta = q_target - q_current
    if delta != 0:
        retry_ladder( market_order(delta) )       # 6 × 5min, then alert; position safe at 1x
        verify_fill_and_books()                   # else kill switch §10.2

# ---- intraday monitor, every 60 s ----
def monitor():
    if pnl_attribution_mismatch() > 0.01*E: flatten(); halt(); alert()   # §10.1
    if margin_or_ADL_warning():                 flatten(); halt(); alert()   # §10.3
    # funding stamps 00/08/16: accounting only, no action
```

## 13. What the backtesting-engineer must test (mandate)

1. **Parity first:** replicate QR's `ret_TG1x_hyst2` daily series from raw data within 1bp/yr cost-equivalent before any overlay work. If parity fails, stop and report.
2. **Horse race (frozen arms):**
   - **A0** = TG1x-hyst2 baseline (QR-parity accounting)
   - **A1** = A0 + VB(10,100,5)  ← primary
   - **A2** = A0 + TS(30)  ← fallback
   - **A3** = A0 + VB × TS (multiplicative)
3. **Windows:** FULL 2020H2–2026 (skip first 200 days, QR convention) and OOS 2022-01-01→2026-10-31. Identical cost model: 5bp taker on |Δ traded|, funding per §9(i); then rerun the selected arm with stamp-exact funding per §9(ii).
4. **Metrics per arm × window:** CAGR, Sharpe, ann vol, MDD, total multiple, round trips/yr, cost drag, funding drag, % gate-on days blocked, plus the 60d-block bootstrap (2000 reps): CAGR CI95, MDD median/worst, and **paired bootstrap vs A0** (ΔMDD, ΔCAGR with p(Δ≤0)).
5. **Frozen selection rule (decided ex-ante; do not re-pick by best CAGR):** A1 ships iff (i) bootstrap MDD median improves ≥ 5pp vs A0, (ii) OOS CAGR ≥ 15%, (iii) OOS Sharpe ≥ A0 Sharpe − 0.10. If A1 fails, evaluate A2 on the same rule; then A3. If all fail, ship A0 unchanged and flag to risk-manager.
6. **Sensitivity surfaces (report only, no re-picking):** X ∈ {80,90,100,110,120}, k ∈ {3,5,10}, τ ∈ {20,25,30,35}. Must reproduce the documented τ=25/30 cliff (`algo_ts_episodes.csv`) and the flat VB surface.
7. **2021 episode detail:** daily equity paths Apr–Dec 2021 for A0–A3 (the design target), incl. exact exit dates/prices vs the A0 gate exit 2021-05-19 @ 36.7k.
8. **Drift deadband check:** confirm the ±5% deadband changes cost drag by < 5bp/yr vs daily drift rebalancing (expected: fewer trades, same exposure within 5%).
9. **Leverage extension (optional arm A4, only if risk-manager requests):** L=1.5 rule from §8, isolated, report liq-distance stats.

## 14. Known failure modes and monitoring KPIs (live)

- **Whipsaw chop at moderate vol (rv10 < 100%):** the overlay's documented blind spot (Aug–Dec 2021). Accepted; bounded by the gate itself.
- **Violent V-bottom rallies:** VB blocks gate entries while vol is elevated — opportunity cost (e.g., parts of Jan–Mar 2021: 63 of 265 gate-on days blocked in 2021). Accepted as insurance premium; ≈5.8% of gate-on days overall.
- **Funding regime shift:** 2021-style 29.5%/yr in-market drag recurs → CAGR compresses toward zero in-market. KPI: trailing 30d annualized funding while held; alert at > 20%/yr (informational only — no rule acts on it; funding-timing alpha is DEAD per QR).
- **Gate statistical fragility** (QR): gate edge vs no-gate p ≈ 0.14–0.25. Not fixable at strategy level; risk-manager sizes accordingly.
- **KPIs to monitor:** daily rv10 (vs 100% threshold), distance of close to both hysteresis bands, position/equity ratio (deadband), funding accrual vs attribution model, bootstrap-consistent rolling MDD vs the −40%/−50% tolerance band.

## 15. Explicit non-goals (v1.0)

No new signal research; no leverage > 1×; no carry parking of idle capital; no intraday execution logic beyond the 00:05 taker shot; no discretionary overrides. Any change to §3 (signal) invalidates this spec and routes back to quant-researcher.
