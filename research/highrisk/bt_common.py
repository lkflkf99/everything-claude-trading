"""bt_common: shared data + signal + overlay + sim code for the backtesting-engineer.

Conventions (locked to QR / algo-strategist traces):
- Panel date t labels the UTC kline day; close[t] prints at 00:00 UTC on day t+1.
- Gate state[t], VB multiplier m_vb[t], TS multiplier m_ts[t] are all DECIDED at
  close[t] and become the HELD weight on day t+1 via sim()'s one-day shift.
  (Matches algo_dd_diag.py: their m[t] applied on day t = m_decided[t-1] here,
  and algo_ts_trace.py likewise; the gate shift matches qr_06_finalize.py.)
- QR-parity accounting: ret[t] = wh[t]*r[t] - wh[t]*fund[t] - TC*|w[t] - wh[t]*(1+r[t])|,
  wh[t] = w[t-1], TC = 5bp.
"""
import pandas as pd, numpy as np, sys
sys.path.insert(0, "research/highrisk")
from qr_utils import perf_stats, max_drawdown

OUT = "research/highrisk"
TC = 0.0005

WINDOWS = [  # (label, start, end, skip_first_n_rows)
    ("FULL_2020H2_2026", "2020-01-01", "2026-10-31", 200),
    ("OOS_2022_2026", "2022-01-01", "2026-10-31", 0),
    ("OOS_2022", "2022-01-01", "2022-12-31", 0),
    ("OOS_2023", "2023-01-01", "2023-12-31", 0),
    ("OOS_2024_2026", "2024-01-01", "2026-10-31", 0),
]


def build_panel():
    """Rebuild the QR daily panel from raw data (parity-verified in bt_00)."""
    pxdf = pd.read_csv("research/data/binance_um_btcusdt_perp_4h.csv", parse_dates=["open_time_utc"])
    px = pxdf.set_index("open_time_utc")["close"].astype(float).sort_index()
    dclose = px.resample("1D").last().dropna()
    dclose.name = "close"
    f = pd.read_csv("research/data/binance_um_btcusdt_perp_funding.csv", parse_dates=["funding_time_utc"])
    f = f.set_index("funding_time_utc").sort_index()
    f["funding_rate"] = f["funding_rate"].astype(float)
    f = f[f.index >= dclose.index[0]]
    fund_sum = f["funding_rate"].resample("1D").sum().rename("fund_sum")
    pan = pd.concat([dclose, fund_sum], axis=1).dropna(subset=["close"])
    pan["ret1"] = pan["close"].pct_change()
    d = pan.dropna(subset=["ret1", "fund_sum"]).copy()
    d["sma200"] = d["close"].rolling(200).mean()
    # rv10: std of ret1[t-9..t], ddof=1, annualized (algo_dd_diag convention)
    d["rv10"] = d["ret1"].rolling(10).std(ddof=1) * np.sqrt(365)
    return d


def gate_hyst(close, sma200):
    """QR-frozen TG1x-hyst2 state machine."""
    hyst = np.zeros(len(close)); state = 0.0
    for t in range(len(close)):
        if np.isnan(sma200[t]):
            hyst[t] = 0.0; continue
        if state == 0.0 and close[t] > 1.02 * sma200[t]:
            state = 1.0
        elif state == 1.0 and close[t] < 0.98 * sma200[t]:
            state = 0.0
        hyst[t] = state
    return hyst


def vb_multiplier(rv10, X=1.00, k=5):
    """Vol circuit breaker multiplier DECIDED at each date (applied next day).

    Returns (m_decided, episodes). Episodes: trigger/rearm in decided-date space.
    """
    n = len(rv10)
    m = np.ones(n)
    state = 1; below = 0
    eps = []; cur = None
    for t in range(n):
        r = rv10[t]
        if not np.isfinite(r):
            m[t] = state; continue
        if state == 1 and r > X:
            state = 0; below = 0
            cur = {"trigger_i": t, "rv10_at_trigger": float(r)}
        elif state == 0:
            if r <= X:
                below += 1
                if below >= k:
                    state = 1; below = 0
                    cur["rearm_i"] = t
                    eps.append(cur); cur = None
            else:
                below = 0
        m[t] = state
    if cur is not None:
        cur["rearm_i"] = None
        eps.append(cur)
    return m, eps


def ts_multiplier(close, gate, tau=0.30):
    """Trailing stop from cycle peak while gated in. DECIDED at each date.

    Replicates algo_ts_trace.py (their m[t] = decided[t-1]).
    """
    n = len(close)
    m = np.ones(n)
    state = 1; peak = -np.inf
    eps = []
    for t in range(n):
        c = close[t]
        if gate[t] == 1:
            if t > 0 and gate[t - 1] == 0:
                peak = c
                if state == 0:
                    state = 1
                    if eps and "rearm_i" not in eps[-1]:
                        eps[-1]["rearm_i"] = t
            peak = max(peak, c)
            if state == 1 and c < (1 - tau) * peak:
                state = 0
                eps.append({"fire_i": t, "close": float(c), "cycle_peak": float(peak),
                            "dd_from_peak_pct": float(100 * (c / peak - 1))})
        m[t] = state
    for e in eps:
        if "rearm_i" not in e:
            e["rearm_i"] = None
    return m, eps


def sim(w_target, r, fund, tc=TC):
    """QR-parity accounting. w_target decided at close[t] -> held day t+1."""
    w = np.nan_to_num(np.asarray(w_target, float), nan=0.0)
    wh = np.concatenate([[0.0], w[:-1]])
    rets = np.zeros(len(w)); turn = np.zeros(len(w))
    for t in range(len(w)):
        turn[t] = abs(w[t] - wh[t] * (1 + r[t]))
        rets[t] = wh[t] * r[t] - wh[t] * fund[t] - tc * turn[t]
    return rets, wh, turn


def window_mask(idx, label, a, b, skip):
    m = (idx >= a) & (idx <= b)
    if skip:
        mm = np.zeros(len(idx), bool); mm[skip:] = True
        m = m & mm
    return m


def arm_metrics(rets, wh, turn, fund, gate, idx, label, a, b, skip):
    m = window_mask(idx, label, a, b, skip)
    ps = perf_stats(rets[m])
    yrs = m.sum() / 365.0
    entries = int(((wh[m] > 0.5) & (np.concatenate([[0.0], wh[:-1]])[m] < 0.5)).sum())
    blocked = int(((wh[m] < 0.5) & (gate[m] > 0.5)).sum())
    gate_on = int((gate[m] > 0.5).sum())
    ps.update({
        "window": label, "n": int(m.sum()),
        "round_trips": entries, "round_trips_per_yr": entries / yrs if yrs > 0 else np.nan,
        "cost_drag_ann_pct": 100 * float((turn[m] * TC).mean() * 365),
        "funding_drag_ann_pct": 100 * float((wh[m] * fund[m]).mean() * 365),
        "avg_w": float(wh[m].mean()),
        "gate_on_days": gate_on, "blocked_gate_on_days": blocked,
        "pct_gate_on_blocked": 100 * blocked / gate_on if gate_on else 0.0,
        "n_trades": int((turn[m] > 1e-12).sum()),
        "turnover_ann": float(turn[m].mean() * 365),
    })
    return ps
