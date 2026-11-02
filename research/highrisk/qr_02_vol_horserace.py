"""qr_02: VOL-TARGET / TREND-GATE / FUNDING-TILT — walk-forward horse race.

Daily rebalance at 00:00 UTC. Signals use day t-1 close info; PnL accrues day t.
ALL strategy parameters frozen a priori (nothing fitted on train windows):
  vol target 50% ann., vol est = rolling 30d daily-ret std * sqrt(365),
  leverage cap 2.0, trend gate = close > 200d SMA,
  tilt = clip(1 - 0.5*fund_z, 0.5, 1.5), final exposure cap 2.0.

Costs: taker 5bp/side on actual rebalanced notional (incl. drift rebalancing).
Funding: long pays w * fund_sum_t daily (can receive when negative).

Strategies:
  (i)   BH        buy & hold 1x
  (ii)  VT50      w = min(2, 0.5/rv30)
  (iii) VT50+TG   (ii) * trend gate
  (iv)  VT50+TG+FT min(2, (ii) * gate * tilt)

Walk-forward OOS windows: 2022, 2023, 2024, 2025-2026 (expanding train shown for
context only -- no fitting occurs, so each test window is genuinely out-of-sample).

Outputs: qr_horserace_windows.csv, qr_horserace_full.csv, qr_horserace_daily.csv,
         qr_horserace_vtgrid.csv (small robustness grid, multiple-testing flagged)
"""
import pandas as pd, numpy as np, json, sys
sys.path.insert(0, "research/highrisk")
from qr_utils import perf_stats

OUT = "research/highrisk"
pan = pd.read_csv(f"{OUT}/qr_daily_panel.csv", index_col=0, parse_dates=True)

TC = 0.0005  # 5bp taker per side

def run_strategy(df, mode, vt=0.50, vol_win=30, cap=2.0):
    """Daily sim. mode in {BH, VT, VT_TG, VT_TG_FT}. Returns df with w, ret_strat, etc."""
    rv = df["ret1"].rolling(vol_win).std() * np.sqrt(365)
    sma = df["close"].rolling(200).mean()
    gate = (df["close"] > sma).astype(float)
    tilt = (1 - 0.5 * df["fund_z"]).clip(0.5, 1.5)
    if mode == "BH":
        w = pd.Series(1.0, index=df.index)
    elif mode == "VT":
        w = (vt / rv).clip(upper=cap)
    elif mode == "VT_TG":
        w = (vt / rv).clip(upper=cap) * gate
    elif mode == "VT_TG_FT":
        w = ((vt / rv).clip(upper=cap) * gate * tilt).clip(upper=cap)
    else:
        raise ValueError(mode)
    w = w.fillna(0.0)
    # position for day t is w[t-1] (set at close of t-1); rebalance at close of day t
    w_held = w.shift(1).fillna(0.0)
    r = df["ret1"].fillna(0.0)
    fund = df["fund_sum"].fillna(0.0)
    gross = w_held * r
    fund_paid = w_held * fund
    eq = np.ones(len(df))
    turn = np.zeros(len(df))
    wv = w.values; wh = w_held.values
    rv_ = r.values; fp_ = fund_paid.values
    for t in range(len(df)):
        # rebalance trade at close of day t: from drifted weight to target w[t]
        drifted = wh[t] * (1 + rv_[t])  # first-order, as fraction of pre-cost equity
        turn[t] = abs(wv[t] - drifted)
        cost = TC * turn[t]
        eq[t] = (eq[t - 1] if t > 0 else 1.0) * (1 + gross.values[t] - fp_[t] - cost) if t > 0 else 1.0
    ret_strat = pd.Series(np.diff(np.concatenate([[1.0], eq])) / np.concatenate([[1.0], eq[:-1]]), index=df.index)
    return pd.DataFrame({"w": w, "w_held": w_held, "gross": gross, "fund_paid": fund_paid,
                         "turnover": turn, "ret": ret_strat, "eq": eq}, index=df.index)

def window_stats(ret, w_held, turn, fund_paid, label, strat):
    r = ret.dropna()
    ps = perf_stats(r.values)
    ps.update({"window": label, "strategy": strat,
               "avg_w": round(float(w_held.mean()), 3),
               "turnover_peryr": round(float(turn.mean() * 365), 2),
               "cost_drag_ann_pct": round(100 * float((turn * TC).mean() * 365), 2),
               "funding_drag_ann_pct": round(100 * float(fund_paid.mean() * 365), 2)})
    return ps

d = pan.dropna(subset=["ret1", "fund_sum"]).copy()
# warm-up: strategies need rv30 (30d) and sma200 (200d); zero-weight before that (BH starts day1)
start_tradable = d.index[200]

MODES = ["BH", "VT", "VT_TG", "VT_TG_FT"]
sims = {m: run_strategy(d, m) for m in MODES}
# BH equity from day1; others effectively start at start_tradable (w=0 before)

WINDOWS = [("2022", "2022-01-01", "2022-12-31"),
           ("2023", "2023-01-01", "2023-12-31"),
           ("2024", "2024-01-01", "2024-12-31"),
           ("2025_2026", "2025-01-01", "2026-10-31"),
           ("FULL_OOS_2022_2026", "2022-01-01", "2026-10-31")]

rows = []
for lbl, a, b in WINDOWS:
    for m in MODES:
        s = sims[m].loc[a:b]
        ps = window_stats(s["ret"], s["w_held"], s["turnover"], s["fund_paid"], lbl, m)
        rows.append(ps)
wf = pd.DataFrame(rows)
for c in ["ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd", "total_x"]:
    wf[c] = wf[c].astype(float).round(3)
wf.to_csv(f"{OUT}/qr_horserace_windows.csv", index=False)
print("=== WALK-FORWARD WINDOWS (net of 5bp taker + funding) ===")
print(wf[["window", "strategy", "n", "ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd",
          "avg_w", "turnover_peryr", "cost_drag_ann_pct", "funding_drag_ann_pct"]].to_string(index=False))

# full-sample (from tradable start, 2020-07-19ish)
rows = []
for m in MODES:
    s = sims[m].loc[start_tradable:]
    ps = window_stats(s["ret"], s["w_held"], s["turnover"], s["fund_paid"], "FULL_2020H2_2026", m)
    rows.append(ps)
fs = pd.DataFrame(rows)
for c in ["ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd", "total_x"]:
    fs[c] = fs[c].astype(float).round(3)
fs.to_csv(f"{OUT}/qr_horserace_full.csv", index=False)
print("\n=== FULL SAMPLE from 200d warmup (net) ===")
print(fs[["window", "strategy", "n", "ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd",
          "avg_w", "turnover_peryr", "cost_drag_ann_pct", "funding_drag_ann_pct"]].to_string(index=False))

# also full period incl. early (BH fair vs managed: managed flat during warmup)
for m in MODES:
    sims[m].to_csv(f"{OUT}/qr_horserace_daily_{m}.csv")

# ---------- small robustness grid on vol target (multiple-testing flagged: 3 variants) ----------
grid = []
for vt in [0.40, 0.50, 0.60]:
    for m in ["VT", "VT_TG", "VT_TG_FT"]:
        s = run_strategy(d, m, vt=vt)
        sub = s.loc["2022-01-01":]
        ps = window_stats(sub["ret"], sub["w_held"], sub["turnover"], sub["fund_paid"],
                          f"OOS_2022_2026_vt{int(vt*100)}", m)
        grid.append(ps)
gd = pd.DataFrame(grid)
for c in ["ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd"]:
    gd[c] = gd[c].astype(float).round(3)
gd.to_csv(f"{OUT}/qr_horserace_vtgrid.csv", index=False)
print("\n=== VT ROBUSTNESS GRID, OOS 2022-2026 (3 variants -> interpret with caution) ===")
print(gd[["window", "strategy", "ann_ret_arith", "cagr", "ann_vol", "sharpe", "mdd", "avg_w"]].to_string(index=False))
