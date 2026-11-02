"""BTCUSDT funding-rate carry strategy — mechanical backtest (frozen spec v1.0).

Delta-neutral: long spot + short USDT-M perp, 1:1 notional, always-on.
Entry once at first bar; exit once at last bar. Upside rebalances on +theta
moves against a reset anchor; downside only sweeps excess margin to reserve.

Documented conventions where the frozen spec leaves room (reported as such):
  * Q rounded DOWN to 0.001 BTC step at entry; rebalance delta = Q/6 also
    rounded DOWN to 0.001 (exchange stepSize); both legs always equal size.
  * Anchor P0 and trigger scan use PERP 4h prices; spot leg executes at SPOT
    4h prices (real basis captured at rebalances).
  * q = position equity / notional = (M + uPnL) / (Q * P); restore q=0.5 after
    each upside rebalance by topping up margin M from spot-sale proceeds.
  * Downside sweep at every non-triggered 4h bar close vs perp close.
  * Liquidation: isolated short, LP = (WB + Q*EP)/(Q*(1+MMR)), MMR=0.5%, cum=0,
    checked every 5m vs mark-price HIGH (perp high as flagged fallback in mark gaps).
  * Funding at floored 00/08/16 UTC stamps, charged iff position held across
    (opened strictly before the stamp). Short receives when F>0: M += Q*mark*F.
    A funding stamp coinciding with a rebalance execution instant is charged on
    the PRE-rebalance size (position that actually crossed the stamp).
  * Entry at 2019-12-31 00:00 bar open (perp open / spot open same instant);
    exit at final bar close (2026-10-31 23:55 bar close), short leg first.
  * Reserve earns 0%. Equity = Q*(P_s - P_p) + Q*EP + M + R.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"        # shared: perp/mark/funding
SPOT_DATA = Path(__file__).resolve().parent / "data"          # carry-specific: spot leg

# ---- frozen spec constants ----
C_CAPITAL = 10_000.0            # allocated capital
N_NOTIONAL = C_CAPITAL / 1.6    # 6,250 design notional
TAKER_SPOT = 0.001              # 0.1%
TAKER_PERP = 0.0005             # 0.05%
MMR = 0.005                     # maintenance margin rate (frozen spec)
LEVERAGE = 2.0                  # isolated 2x -> margin = 0.5 * notional
STEP = 0.001                    # BTC stepSize
THETA_BASE = 0.20               # upside rebalance trigger
H4_MS = 4 * 3_600 * 1000
DAY_MS = 86_400_000
YEAR_MS = 365 * DAY_MS


# ============================ pure mechanics (unit-tested) ============================

def floor_step(x: float, step: float = STEP) -> float:
    """Round down to exchange step size."""
    return math.floor(x / step + 1e-12) * step


def liq_price_short(WB: float, Q: float, EP: float, mmr: float = MMR) -> float:
    """Isolated short liquidation price (cum=0): LP = (WB + Q*EP)/(Q*(1+MMR))."""
    return (WB + Q * EP) / (Q * (1.0 + mmr))


def funding_cashflow(Q: float, mark: float, F: float) -> float:
    """Cashflow to a SHORT of size Q at a funding stamp: +Q*mark*F (receives if F>0)."""
    return Q * mark * F


def rebalance_math(Q: float, M: float, R: float, EP: float, pe_s: float, pe_p: float,
                   taker_spot: float = TAKER_SPOT, taker_perp: float = TAKER_PERP,
                   draw_from_reserve: bool = True):
    """Upside rebalance at execution prices pe_s (spot) / pe_p (perp).

    Sell d=Q/6 spot, buy-to-close d short, then restore q=0.5 (position equity /
    notional) on the remaining position: top up margin from spot-sale proceeds
    first; if proceeds fall short (execution price above the exact trigger), draw
    the remainder from the strategy reserve R (the spec's 0.1N buffer + swept
    carry). If both are insufficient, transfer everything and flag unmet.

    q is interpreted as position-equity/notional = (M + uPnL)/(Q*P): the only
    reading under which the isolated short stays solvent (see report).
    """
    d = floor_step(Q / 6.0)
    if d < STEP:
        return None
    Qn = round(Q - d, 10)
    fee_s = d * pe_s * taker_spot
    proceeds_s = d * pe_s - fee_s                        # spot sale proceeds net of fee
    fee_p = d * pe_p * taker_perp
    M_after_close = M + d * (EP - pe_p) - fee_p          # realized short PnL into margin
    uPnL = Qn * (EP - pe_p)
    target_eq = 0.5 * Qn * pe_p                          # q=0.5 on remaining notional
    X = target_eq - (M_after_close + uPnL)               # margin top-up needed
    X_need = max(X, 0.0)
    X_from_proceeds = min(X_need, proceeds_s)
    shortfall = X_need - X_from_proceeds
    X_from_R = min(shortfall, R) if draw_from_reserve else 0.0
    unmet = shortfall - X_from_R
    Mn = M_after_close + X_from_proceeds + X_from_R
    Rn = R + (proceeds_s - X_from_proceeds) - X_from_R
    return {"d": d, "Q": Qn, "M": Mn, "R": Rn, "X": X_from_proceeds + X_from_R,
            "X_from_proceeds": X_from_proceeds, "X_from_R": X_from_R,
            "unmet": unmet, "X_unclipped": X, "proceeds_s": proceeds_s,
            "fee_p": fee_p, "fee_s": fee_s, "uPnL_after": uPnL}


def extraction_math(Q: float, M: float, EP: float, P: float):
    """Downside sweep at price P: withdraw excess margin above q=0.5 to reserve.

    Returns (w, bind_flag): w >= 0 withdrawal (0 if no excess); bind_flag True if
    the wallet-balance cap (w <= M) was binding. Position size unchanged.

    NOTE (spec contradiction, see report): this literal reading strips the margin
    wallet on the way down; LP then tracks ~1.49x of the DECLINING price and is
    run over by any V-shaped recovery (first instance: 2020-04-02). Kept as the
    spec-literal evidence path (sweep_mode='q05').
    """
    eq = M + Q * (EP - P)
    excess = eq - 0.5 * Q * P
    if excess <= 0:
        return 0.0, False
    w = min(excess, M)
    return w, bool(w < excess - 1e-12)


def sweep_carry_math(M: float, M_floor: float) -> float:
    """Proposed minimal-fix sweep: withdraw only inflows above the rebalance-
    anchored margin floor (i.e., accumulated carry), never principal or uPnL.

    w = max(0, M - M_floor). Position size unchanged; LP never drops below its
    post-rebalance level (modulo negative-funding drains).
    """
    return max(0.0, M - M_floor)


def floor_funding_ts(ts_ms: int) -> int:
    """Floor a funding timestamp (ms jitter) down to its hour slot."""
    return (int(ts_ms) // 3_600_000) * 3_600_000


# ============================ data loading ============================

def load_data():
    perp5 = pd.read_csv(DATA / "binance_um_btcusdt_perp_5m.csv",
                        usecols=["open_time_ms", "open", "high", "low", "close"])
    p4 = pd.read_csv(DATA / "binance_um_btcusdt_perp_4h.csv")
    s4 = pd.read_csv(SPOT_DATA / "binance_spot_btcusdt_4h.csv")
    mark5 = pd.read_csv(DATA / "binance_um_btcusdt_perp_mark_5m.csv",
                        usecols=["open_time_ms", "high", "close"])
    fun = pd.read_csv(DATA / "binance_um_btcusdt_perp_funding.csv")
    spot1 = pd.read_csv(SPOT_DATA / "binance_spot_btcusdt_1h.csv",
                        usecols=["open_time_ms", "open", "close"])
    return perp5, p4, s4, mark5, fun, spot1


def build_funding(fun: pd.DataFrame, mark5: pd.DataFrame, perp5: pd.DataFrame):
    """Funding events: floored ts, rate F, mark price (CSV -> mark5 close -> perp close)."""
    f = fun.copy()
    f["ts"] = f["funding_time_ms"].map(floor_funding_ts)
    f = f.drop_duplicates(subset="ts", keep="first").sort_values("ts").reset_index(drop=True)
    grid_ok = bool((f["ts"] % (8 * 3_600_000) == 0).all())
    mark_close = dict(zip(mark5["open_time_ms"], mark5["close"]))
    perp_close = dict(zip(perp5["open_time_ms"], perp5["close"]))
    marks, src = [], {"csv": 0, "mark5": 0, "perp5": 0, "missing": 0}
    for ts, mp in zip(f["ts"], f["mark_price"]):
        if pd.notna(mp):
            marks.append(float(mp)); src["csv"] += 1
        elif ts in mark_close:
            marks.append(mark_close[ts]); src["mark5"] += 1
        elif ts in perp_close:
            marks.append(perp_close[ts]); src["perp5"] += 1
        else:
            marks.append(np.nan); src["missing"] += 1
    f["mark"] = marks
    return f, grid_ok, src


# ============================ main backtest ============================

def run_backtest(theta: float = THETA_BASE, exec_mode: str = "close",
                 scan: str = "high", reserve_backstop: bool = True,
                 sweep_mode: str = "carry", terminate_on_liq: bool = False,
                 collect_curve: bool = True):
    """Run the frozen-spec carry backtest. Returns a results dict.

    reserve_backstop=True is the faithful reading of "恢復 q=0.5": margin is
    fully restored at each rebalance, drawing the reserve if spot proceeds fall
    short. reserve_backstop=False is the literal proceeds-only reading.
    sweep_mode='q05' is the spec-literal down-sweep (evidence path; structurally
    liquidates in V-recoveries). sweep_mode='carry' is the PROPOSED minimal fix:
    sweep only inflows above the rebalance-anchored margin floor (no compounding
    of carry into the position; principal/uPnL never swept).
    terminate_on_liq truncates the strategy at the first 5m liquidation hit with
    conservative terminal accounting (margin residual ~= 0, spot sold at the
    containing hour's close, taker fee).
    """
    perp5, p4, s4, mark5, fun, spot1 = load_data()
    f, grid_ok, mark_src = build_funding(fun, mark5, perp5)

    t0 = int(perp5["open_time_ms"].iloc[0])
    t_end = int(perp5["open_time_ms"].iloc[-1])
    P_p0 = float(perp5["open"].iloc[0])
    P_s0 = float(spot1.loc[spot1["open_time_ms"] == t0, "open"].iloc[0])

    # --- aligned 4h panel: perp complete bars left-join spot 4h ---
    panel = p4.merge(s4, on="open_time_ms", how="left", suffixes=("_p", "_s"))
    panel = panel[(panel["open_time_ms"] >= t0) & (panel["open_time_ms"] <= t_end)].reset_index(drop=True)
    n_spot_missing = int(panel["close_s"].isna().sum())
    n_panel_bars = len(panel)

    # --- entry ---
    Q = floor_step(N_NOTIONAL / P_p0)
    EP = P_p0
    Q_entry = Q
    fee_s_entry = Q * P_s0 * TAKER_SPOT
    fee_p_entry = Q * P_p0 * TAKER_PERP
    M = 0.5 * N_NOTIONAL
    R = C_CAPITAL - Q * P_s0 - fee_s_entry - M - fee_p_entry
    R0_entry = R
    P0 = P_p0  # anchor = entry price

    fw = f[(f["ts"] > t0) & (f["ts"] <= t_end)]          # funding chargeable in-window
    funding_map = dict(zip(fw["ts"], zip(fw["funding_rate"], fw["mark"])))

    # --- unified event timeline: funding stamps + 4h bar checks ---
    tl = [(int(ts), 0, -1) for ts in fw["ts"]]           # priority 0: funding first on ties
    for i, row in enumerate(panel.itertuples()):
        tl.append((int(row.open_time_ms), 1, i))         # priority 1: bar check
    tl.sort(key=lambda x: (x[0], x[1]))

    bars = panel[["open_time_ms", "open_p", "high_p", "close_p", "open_s", "close_s"]].to_numpy()
    next_open_p = panel["open_p"].shift(-1).to_numpy()
    next_open_s = panel["open_s"].shift(-1).to_numpy()
    next_ts = panel["open_time_ms"].shift(-1).to_numpy()

    events = [(t0, Q, M, R)]                              # (eff_ts, Q, M, R)
    rebal_log, extract_log, funding_applied = [], [], []
    applied_fund: set[int] = set()
    skipped_rebals = skipped_nan = extract_binds = 0
    unmet_shortfalls = n_reserve_draws = 0
    reserve_draw_total = 0.0
    M_floor = M                                           # rebalance-anchored margin floor

    def apply_funding(ts: int):
        nonlocal M
        if ts in funding_map and ts not in applied_fund:
            applied_fund.add(ts)
            F, mk = funding_map[ts]
            if not np.isnan(mk):
                cf = funding_cashflow(Q, mk, F)
                M += cf
                funding_applied.append((ts, Q, mk, F, cf))
                events.append((ts, Q, M, R))

    for ts, kind, i in tl:
        if kind == 0:
            apply_funding(ts)
            continue
        t, o_p, h_p, c_p, o_s, c_s = bars[i]
        t = int(t)
        trig = (h_p >= (1.0 + theta) * P0) if scan == "high" else (c_p >= (1.0 + theta) * P0)
        if trig:
            if exec_mode == "close":
                pe_p, pe_s, eff = c_p, c_s, t + H4_MS
            else:
                if np.isnan(next_ts[i]):
                    continue
                pe_p, pe_s, eff = next_open_p[i], next_open_s[i], int(next_ts[i])
            if np.isnan(pe_s) or np.isnan(pe_p):
                skipped_nan += 1
                continue
            apply_funding(eff)          # stamp at exec instant charges the OLD size
            rb = rebalance_math(Q, M, R, EP, pe_s, pe_p,
                                draw_from_reserve=reserve_backstop)
            if rb is None:
                skipped_rebals += 1
                continue
            Q, M, R = rb["Q"], rb["M"], rb["R"]
            P0 = pe_p
            M_floor = M
            unmet_shortfalls += int(rb["unmet"] > 1e-9)
            n_reserve_draws += int(rb["X_from_R"] > 1e-9)
            reserve_draw_total += rb["X_from_R"]
            rebal_log.append({"eff_ts": eff, "trigger_ts": t, "exec_p_perp": float(pe_p),
                              "exec_p_spot": float(pe_s), "delta": rb["d"], "Q_after": Q,
                              "fee_s": rb["fee_s"], "fee_p": rb["fee_p"],
                              "X_to_margin": rb["X"], "X_from_R": rb["X_from_R"],
                              "unmet": rb["unmet"], "P0_after": P0})
            events.append((eff, Q, M, R))
        else:
            apply_funding(t + H4_MS)    # stamp at bar-close instant first (commutes)
            if sweep_mode == "q05":     # spec-literal (evidence path)
                w, bind = extraction_math(Q, M, EP, c_p)
            else:                       # proposed minimal fix: sweep carry only
                w, bind = sweep_carry_math(M, M_floor), False
            if w > 0:
                M -= w
                R += w
                extract_binds += int(bind)
                extract_log.append((t + H4_MS, w, c_p))
                events.append((t + H4_MS, Q, M, R))

    # --- exit at final bar close: short first, then spot ---
    perp_close_end = float(perp5["close"].iloc[-1])
    spot_last = spot1[spot1["open_time_ms"] <= t_end].iloc[-1]
    P_s_end = float(spot_last["close"])
    Q_end = Q
    fee_p_exit = Q * perp_close_end * TAKER_PERP
    M += Q * (EP - perp_close_end) - fee_p_exit
    R += M                                            # isolated wallet released
    M = 0.0
    fee_s_exit = Q * P_s_end * TAKER_SPOT
    R += Q * P_s_end - fee_s_exit
    E_end = R
    events.append((t_end, 0.0, 0.0, R))

    # ================= event-sourced state series =================
    order = np.argsort(np.array([e[0] for e in events], dtype=np.int64), kind="stable")
    ev_ts = np.array([events[i][0] for i in order], dtype=np.int64)
    ev_Q = np.array([events[i][1] for i in order], dtype=float)
    ev_M = np.array([events[i][2] for i in order], dtype=float)
    ev_R = np.array([events[i][3] for i in order], dtype=float)
    LP_ev = np.where(ev_Q > 0, liq_price_short(ev_M, ev_Q, EP), np.inf)

    # ================= liquidation check: 5m mark high vs LP =================
    mk = mark5[(mark5["open_time_ms"] >= t0) & (mark5["open_time_ms"] <= t_end)]
    idx = np.clip(np.searchsorted(ev_ts, mk["open_time_ms"].to_numpy(), side="right") - 1,
                  0, len(ev_ts) - 1)
    lp_bar, q_bar = LP_ev[idx], ev_Q[idx]
    mark_high = mk["high"].to_numpy()
    n_liq = int(((q_bar > 0) & (mark_high >= lp_bar)).sum())
    dist = np.where(q_bar > 0, lp_bar / mark_high - 1.0, np.inf)
    dist_df = pd.DataFrame({"ts": mk["open_time_ms"].to_numpy(), "dist": dist, "proxy": False})

    # mark-gap fallback: perp 5m high as proxy, flagged
    p5 = perp5[(perp5["open_time_ms"] >= t0) & (perp5["open_time_ms"] <= t_end)]
    gap_mask = ~p5["open_time_ms"].isin(set(mk["open_time_ms"])).to_numpy()
    n_gap_bars = int(gap_mask.sum())
    n_liq_gap = 0
    if n_gap_bars:
        gp = p5[gap_mask]
        idxg = np.clip(np.searchsorted(ev_ts, gp["open_time_ms"].to_numpy(), side="right") - 1,
                       0, len(ev_ts) - 1)
        lpg, qg = LP_ev[idxg], ev_Q[idxg]
        n_liq_gap = int(((qg > 0) & (gp["high"].to_numpy() >= lpg)).sum())
        distg = np.where(qg > 0, lpg / gp["high"].to_numpy() - 1.0, np.inf)
        dist_df = pd.concat([dist_df, pd.DataFrame({"ts": gp["open_time_ms"].to_numpy(),
                                                    "dist": distg, "proxy": True})],
                            ignore_index=True)
    dist_df = dist_df.sort_values("ts").reset_index(drop=True)
    imin = int(dist_df["dist"].argmin())
    min_liq_dist = float(dist_df["dist"].iloc[imin])
    min_liq_date = str(pd.Timestamp(dist_df["ts"].iloc[imin], unit="ms", tz="UTC"))
    min_liq_proxy = bool(dist_df["proxy"].iloc[imin])

    # ---- termination at first liquidation (spec-literal evidence run) ----
    liq_hits_df = dist_df[dist_df["dist"] <= 0]
    first_liq_ts = int(liq_hits_df["ts"].iloc[0]) if len(liq_hits_df) else None
    terminated = bool(terminate_on_liq and first_liq_ts is not None)
    t_cut = first_liq_ts if terminated else t_end
    E_term = None
    termination = None
    if terminated:
        iq = int(np.clip(np.searchsorted(ev_ts, first_liq_ts, side="right") - 1, 0, len(ev_ts) - 1))
        Q_l, M_l, R_l = float(ev_Q[iq]), float(ev_M[iq]), float(ev_R[iq])
        LP_l = float(LP_ev[iq])
        P_s_liq = float(spot1[spot1["open_time_ms"] <= first_liq_ts]["close"].iloc[-1])
        margin_resid = max(0.0, M_l + Q_l * (EP - LP_l) - MMR * Q_l * LP_l)  # = 0 by LP definition
        E_term = R_l + Q_l * P_s_liq * (1.0 - TAKER_SPOT) + margin_resid
        termination = {"t_liq": str(pd.Timestamp(first_liq_ts, unit="ms", tz="UTC")),
                       "LP": round(LP_l, 2), "Q": Q_l, "M_before": round(M_l, 2),
                       "R_before": round(R_l, 2), "spot_px": P_s_liq,
                       "margin_residual": round(margin_resid, 4),
                       "E_terminal": round(E_term, 2),
                       "note": "short force-closed at LP; maintenance margin consumed by clearance; spot leg sold at containing-hour close (taker)"}

    # ================= daily equity curve =================
    p5d = p5.copy()
    p5d["date"] = (p5d["open_time_ms"] // DAY_MS).astype(int)
    perp_day = p5d.groupby("date").agg(ts=("open_time_ms", "last"), close=("close", "last"))
    spot1x = spot1.copy()
    spot1x["date"] = (spot1x["open_time_ms"] // DAY_MS).astype(int)
    spot_day = spot1x.groupby("date")["close"].last()
    days = perp_day.index.to_numpy()
    ts_eval = perp_day["ts"].to_numpy()
    idxe = np.clip(np.searchsorted(ev_ts, ts_eval, side="right") - 1, 0, len(ev_ts) - 1)
    Qe, Me, Re = ev_Q[idxe], ev_M[idxe], ev_R[idxe]
    pe = perp_day["close"].to_numpy()
    se = spot_day.reindex(days).ffill().to_numpy()
    E = Qe * (se - pe) + Qe * EP + Me + Re
    eq = pd.DataFrame({"date": pd.to_datetime(days * DAY_MS, unit="ms", utc=True),
                       "ts_eval": ts_eval, "equity": E, "Q": Qe, "M": Me, "R": Re,
                       "perp_close": pe, "spot_close": se})
    if terminated:
        eq = eq[eq["ts_eval"] <= t_cut].copy()
        term_row = {"date": pd.Timestamp(first_liq_ts, unit="ms", tz="UTC"),
                    "ts_eval": first_liq_ts, "equity": E_term, "Q": 0.0, "M": 0.0,
                    "R": E_term, "perp_close": np.nan, "spot_close": np.nan}
        eq = pd.concat([eq, pd.DataFrame([term_row])], ignore_index=True)
    E = eq["equity"].to_numpy()
    dE = np.diff(E, prepend=E[0])

    # ================= headline stats =================
    E_final = E_term if terminated else E_end
    days_total = (t_cut - t0) / DAY_MS
    years = days_total / 365.0
    pnl = E_final - C_CAPITAL
    fee_entry = fee_s_entry + fee_p_entry
    fee_exit = 0.0 if terminated else fee_p_exit + fee_s_exit
    rebal_costs = float(sum(r["fee_s"] + r["fee_p"] for r in rebal_log if r["eff_ts"] <= t_cut))
    funding_total = float(sum(x[4] for x in funding_applied if x[0] <= t_cut))
    funding_pos = float(sum(x[4] for x in funding_applied if x[4] > 0 and x[0] <= t_cut))
    funding_neg = float(sum(x[4] for x in funding_applied if x[4] < 0 and x[0] <= t_cut))

    ret_d = dE / C_CAPITAL
    sharpe = float(ret_d.mean() / ret_d.std(ddof=1) * math.sqrt(365)) if ret_d.std(ddof=1) > 0 else np.nan
    run_max = np.maximum.accumulate(E)
    dd = E / run_max - 1.0
    maxdd = float(dd.min())
    maxdd_usd = float((E - run_max).min())
    imdd = int(np.argmin(dd))

    # Newey-West t-stat on daily net PnL (lag 10) + plain t
    x = dE
    n_ = len(x)
    xbar = float(x.mean())
    g0 = float(((x - xbar) ** 2).mean())
    L = 10
    nw = g0
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        nw += 2 * w * float(((x[l:] - xbar) * (x[:-l] - xbar)).mean())
    se = math.sqrt(nw / n_)
    t_nw = float(xbar / se) if se > 0 else np.nan
    t_plain = float(xbar / (x.std(ddof=1) / math.sqrt(n_)))

    # ================= negative funding stretches =================
    fw = fw[fw["ts"] <= t_cut]
    neg = (fw["funding_rate"] < 0).to_numpy()
    fw_list = fw.reset_index(drop=True)
    stretches, start = [], None
    for i, v in enumerate(neg):
        if v and start is None:
            start = i
        if start is not None and (not v or i == len(neg) - 1):
            end = i if v else i - 1
            seg = fw_list.iloc[start:end + 1]
            stretches.append({
                "start": str(pd.Timestamp(seg["ts"].iloc[0], unit="ms", tz="UTC")),
                "end": str(pd.Timestamp(seg["ts"].iloc[-1], unit="ms", tz="UTC")),
                "n_events": int(end - start + 1),
                "days": round(float((seg["ts"].iloc[-1] - seg["ts"].iloc[0]) / DAY_MS) + 1 / 3, 2),
                "cum_bp": round(float(seg["funding_rate"].sum() * 1e4), 2),
            })
            start = None
    stretches.sort(key=lambda s: s["cum_bp"])

    # ================= circuit breaker: rolling-90d ann carry < 0 for >= 60d =================
    f_all = f.sort_values("ts").reset_index(drop=True)
    rates = f_all["funding_rate"].to_numpy()
    ts_f = f_all["ts"].to_numpy()
    n90 = 90 * 3
    roll_sum = pd.Series(rates).rolling(n90, min_periods=n90).sum().to_numpy()
    ann_carry = roll_sum * (365.0 / 90.0)
    cb_triggers, ep_start = [], None
    for i in range(len(ts_f)):
        v = ann_carry[i]
        if np.isnan(v):
            continue
        if v < 0 and ep_start is None:
            ep_start = i
        elif v >= 0:
            ep_start = None
        if ep_start is not None and t0 < ts_f[i] <= t_cut:
            dur_days = (ts_f[i] - ts_f[ep_start]) / DAY_MS
            if dur_days >= 60:
                ep_key = str(pd.Timestamp(ts_f[ep_start], unit="ms", tz="UTC"))
                if not cb_triggers or cb_triggers[-1]["episode_start"] != ep_key:
                    cb_triggers.append({
                        "trigger_ts": str(pd.Timestamp(ts_f[i], unit="ms", tz="UTC")),
                        "episode_start": ep_key,
                        "ann_carry_at_trigger": round(float(v) * 1e4, 2),  # bp/yr
                    })

    # ================= segments =================
    eqi = eq.set_index("date")

    def seg_pnl(a, b):
        s = eqi[(eqi.index >= pd.Timestamp(a, tz="UTC")) & (eqi.index < pd.Timestamp(b, tz="UTC"))]
        if len(s) < 2:
            return None
        pnl_seg = float(s["equity"].iloc[-1] - s["equity"].iloc[0])
        yrs = (s["ts_eval"].iloc[-1] - s["ts_eval"].iloc[0]) / YEAR_MS
        ta, tb = s["ts_eval"].iloc[0], s["ts_eval"].iloc[-1]
        rb_seg = [r for r in rebal_log if ta <= r["eff_ts"] <= tb]
        return {"pnl": round(pnl_seg, 2), "years": round(yrs, 3),
                "ann_on_N": pnl_seg / N_NOTIONAL / yrs if yrs > 0 else np.nan,
                "ann_on_C": pnl_seg / C_CAPITAL / yrs if yrs > 0 else np.nan,
                "n_rebal": len(rb_seg),
                "rebal_cost": round(float(sum(r["fee_s"] + r["fee_p"] for r in rb_seg)), 2),
                "funding": round(float(sum(x[4] for x in funding_applied if ta < x[0] <= tb)), 2)}

    per_year = {}
    for y in sorted(set(eqi.index.year)):
        r = seg_pnl(f"{y}-01-01", f"{y + 1}-01-01")
        if r:
            per_year[str(y)] = r

    segs = {"pre_breakpoint": seg_pnl("2019-12-31", "2025-09-18"),
            "post_breakpoint": seg_pnl("2025-09-18", "2026-11-01"),
            "covid_2020": seg_pnl("2020-02-20", "2020-04-01"),
            "bull_2021": seg_pnl("2020-10-01", "2021-05-01"),
            "bear_2022": seg_pnl("2022-01-01", "2023-01-01")}

    def min_dist_in(a, b):
        tsa = int(pd.Timestamp(a, tz="UTC").timestamp() * 1000)
        tsb = int(pd.Timestamp(b, tz="UTC").timestamp() * 1000)
        s = dist_df[(dist_df["ts"] >= tsa) & (dist_df["ts"] < tsb)]
        return round(float(s["dist"].min()), 4) if len(s) else None

    stress_dist = None if terminated else {
        "covid_2020": min_dist_in("2020-02-20", "2020-04-01"),
        "bull_2021": min_dist_in("2020-10-01", "2021-05-01"),
        "bear_2022": min_dist_in("2022-01-01", "2023-01-01")}

    results = {
        "config": {"theta": theta, "exec_mode": exec_mode, "scan": scan,
                   "reserve_backstop": reserve_backstop, "sweep_mode": sweep_mode,
                   "terminate_on_liq": terminate_on_liq},
        "entry": {"t0": str(pd.Timestamp(t0, unit="ms", tz="UTC")), "P_p0": P_p0, "P_s0": P_s0,
                  "Q": Q_entry, "N_realized": round(Q_entry * P_p0, 2), "M0": 0.5 * N_NOTIONAL,
                  "R0": round(R0_entry, 2), "fee_entry": round(fee_entry, 2)},
        "exit": None if terminated else
                {"t_end": str(pd.Timestamp(t_end, unit="ms", tz="UTC")), "perp_close": perp_close_end,
                 "spot_close": P_s_end, "Q_end": Q_end, "fee_exit": round(fee_exit, 2)},
        "terminated": terminated, "termination": termination,
        "first_liq_ts": (str(pd.Timestamp(first_liq_ts, unit="ms", tz="UTC"))
                         if first_liq_ts is not None else None),
        "years": round(years, 3), "days": days_total,
        "E_end": round(float(E_final), 2), "pnl": round(float(pnl), 2),
        "ret_on_N": round(float(pnl / N_NOTIONAL), 4), "ret_on_C": round(float(pnl / C_CAPITAL), 4),
        "ann_on_N": round(float(pnl / N_NOTIONAL / years), 5),
        "ann_on_C": round(float(pnl / C_CAPITAL / years), 5),
        "sharpe_daily_C": round(sharpe, 3), "maxdd_pct": round(maxdd, 5),
        "maxdd_usd": round(maxdd_usd, 2), "maxdd_date": str(eqi.index[imdd].date()),
        "t_nw10": round(t_nw, 2), "t_plain": round(t_plain, 2),
        "funding_total": round(funding_total, 2), "funding_pos": round(funding_pos, 2),
        "funding_neg": round(funding_neg, 2),
        "n_funding_events": len([x for x in funding_applied if x[0] <= t_cut]),
        "n_rebalances": len([r for r in rebal_log if r["eff_ts"] <= t_cut]),
        "rebal_costs": round(rebal_costs, 2),
        "skipped_rebals": skipped_rebals, "skipped_nan_spot": skipped_nan,
        "n_reserve_draws": n_reserve_draws, "reserve_draw_total": round(reserve_draw_total, 2),
        "unmet_shortfalls": unmet_shortfalls, "extract_binds": extract_binds,
        "n_extractions": len([x for x in extract_log if x[0] <= t_cut]),
        "extract_total": round(float(sum(x[1] for x in extract_log if x[0] <= t_cut)), 2),
        "fee_entry": round(fee_entry, 2), "fee_exit": round(fee_exit, 2),
        "n_liq_mark": int((dist_df[(~dist_df["proxy"]) & (dist_df["ts"] <= t_cut)]["dist"] <= 0).sum()),
        "n_liq_gap_proxy": int((dist_df[(dist_df["proxy"]) & (dist_df["ts"] <= t_cut)]["dist"] <= 0).sum()),
        "min_liq_dist": min_liq_dist, "min_liq_date": min_liq_date, "min_liq_proxy": min_liq_proxy,
        "n_gap_bars_proxy": n_gap_bars,
        "spot4h_missing": n_spot_missing, "panel_4h_bars": n_panel_bars,
        "funding_grid_ok": grid_ok, "mark_src": mark_src,
        "neg_stretches_top5": stretches[:5], "n_neg_stretches": len(stretches),
        "cb_triggers": cb_triggers, "n_cb_triggers": len(cb_triggers),
        "per_year": per_year, "segments": segs, "stress_min_liq_dist": stress_dist,
    }
    if collect_curve:
        results["_eq"] = eq
        results["_rebal_log"] = pd.DataFrame(rebal_log)
        results["_funding_applied"] = pd.DataFrame(funding_applied, columns=["ts", "Q", "mark", "F", "cf"])
        results["_dist_df"] = dist_df
        results["_events"] = pd.DataFrame({"eff_ts": ev_ts, "Q": ev_Q, "M": ev_M, "R": ev_R,
                                           "LP": LP_ev})
    return results


if __name__ == "__main__":
    import sys
    theta = float(sys.argv[1]) if len(sys.argv) > 1 else THETA_BASE
    exec_mode = sys.argv[2] if len(sys.argv) > 2 else "close"
    scan = sys.argv[3] if len(sys.argv) > 3 else "high"
    res = run_backtest(theta, exec_mode, scan, collect_curve=False)
    print(json.dumps({k: v for k, v in res.items() if not k.startswith("_")}, indent=2, default=str))
