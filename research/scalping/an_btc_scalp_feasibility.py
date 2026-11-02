#!/usr/bin/env python3
"""Feasibility of the BTCUSDT 5m momentum scalp spec.

Pre-committed measurement, not a strategy search and not the readme's
embedded equity curve (that code is misspecified and is not run).

Definitions
- Signal on the closed 5m bar, indicators use only data through that close.
- EMA/MACD: span ewm, adjust=False (alpha = 2/(span+1)).
- RSI(14) and ATR(14): Wilder recursion, SMA seed of the first 14 changes.
- VWAP: typical price (H+L+C)/3, reset at 00:00 UTC each day.
  Never-reset cumsum VWAP is a bug check only.
- Fresh entry: signal transitions 0 -> +1 or 0 -> -1. Bars that stay on
  are not new trades. Direct +/-1 flips are reported only as a sensitivity.
- Forward simple return at horizon h: side * (close[t+h] / close[t] - 1),
  which assumes a fill at the signal close. Next-open fill is also reported:
  side * (close[t+h] / open[t+1] - 1). Windows that cross a missing 5m bar
  are dropped.
- Realistic round-trip cost: VIP0 taker/taker = 5 bp + 5 bp = 10 bp of price.
  Optimistic maker/maker = 2 bp + 2 bp = 4 bp of price.
- Stop/TP: entry at signal close, barriers on the next 24 trade high/lows.
  Stop = 2*ATR, 1.5R = 3*ATR, 2R = 4*ATR. Same-bar ties count as a stop.
- Liquidation: isolated 5x, tier-1 MMR 0.40%, cum 0.
  Long adverse distance = (1/L - MMR) / (1 - MMR).
  Short adverse distance = (1/L - MMR) / (1 + MMR).
  Trigger is mark high/low, not last price.

No orders are sent. No statistic in the outputs is typed by hand.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
DATA = RESEARCH / "data"
OUT = HERE

TRADE_PATH = DATA / "binance_um_btcusdt_perp_5m.csv"
MARK_PATH = DATA / "binance_um_btcusdt_perp_mark_5m.csv"
FUND_PATH = DATA / "binance_um_btcusdt_perp_funding.csv"

WARMUP = 200
BAR_MS = 300_000
HORIZONS = (1, 3, 6, 12, 24)
HORIZON_LABEL = {1: "5m", 3: "15m", 6: "30m", 12: "1h", 24: "2h"}

# VIP0 USD-M, exchange_specs.md snapshot 2026-11-02. Inputs, not estimates.
TAKER_FEE = 0.0005  # 5 bp per side
MAKER_FEE = 0.0002  # 2 bp per side
README_TAKER_FEE = 0.0004  # code default, optimistic vs the verified 5 bp
README_MAKER_FEE = 0.0002
README_SLIP = 0.0001
MMR = 0.004
LEVERAGE = 5.0
RT_TAKER = 2.0 * TAKER_FEE  # 10 bp
RT_MAKER = 2.0 * MAKER_FEE  # 4 bp
RT_README_TAKER = 2.0 * README_TAKER_FEE  # 8 bp
README_BLEND_ONE_WAY = 0.8 * README_MAKER_FEE + 0.2 * README_TAKER_FEE  # 2.4 bp
RT_README_BLEND = 2.0 * README_BLEND_ONE_WAY  # 4.8 bp
VIP0_BLEND_ONE_WAY = 0.8 * MAKER_FEE + 0.2 * TAKER_FEE  # 2.6 bp
RT_VIP0_BLEND = 2.0 * VIP0_BLEND_ONE_WAY  # 5.2 bp
RT_MAKER_IN_TAKER_OUT = MAKER_FEE + TAKER_FEE  # 7 bp
LONG_LIQ = (1.0 / LEVERAGE - MMR) / (1.0 - MMR)
SHORT_LIQ = (1.0 / LEVERAGE - MMR) / (1.0 + MMR)
LIQ_19_7 = 0.197


def bp(x: float) -> float:
    return float(x) * 1e4


def wilder_smooth(x: np.ndarray, period: int) -> np.ndarray:
    """Wilder smoothing. Seed at index `period` is the SMA of x[1:period+1]."""
    x = np.asarray(x, dtype=np.float64)
    n = x.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    if n <= period:
        return out
    inv = 1.0 / period
    c = 1.0 - inv
    s = 0.0
    for i in range(1, period + 1):
        s += x[i]
    s *= inv
    out[period] = s
    for i in range(period + 1, n):
        s = c * s + inv * x[i]
        out[i] = s
    return out


def window_ok(step: np.ndarray, h: int) -> np.ndarray:
    """step[i] == 1 iff bar i is exactly 5 minutes after bar i-1.

    ok[i] is True when the h steps (i+1)..(i+h) are all exact 5-minute steps.
    """
    n = step.shape[0]
    ok = np.zeros(n, dtype=bool)
    if h <= 0 or h >= n:
        return ok
    c = np.cumsum(step, dtype=np.int64)
    ok[: n - h] = (c[h:] - c[: n - h]) == h
    return ok


def run_lengths(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    m = np.asarray(mask, dtype=np.int8)
    n = m.shape[0]
    dm = np.empty(n + 1, dtype=np.int8)
    dm[0] = m[0] if n else 0
    if n:
        dm[1:-1] = m[1:] - m[:-1]
        dm[-1] = -m[-1]
    else:
        dm[-1] = 0
    starts = np.flatnonzero(dm == 1)
    ends = np.flatnonzero(dm == -1)
    return starts, ends - starts


def nw_mean_se(x: np.ndarray, lags: int) -> tuple[float, float, int]:
    """Return (mean, se_of_mean, fallback_flag). Bartlett Newey-West."""
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 5:
        return float("nan"), float("nan"), 1
    mean = float(x.mean())
    e = x - mean
    g0 = float(np.dot(e, e) / n)
    lags = int(max(0, min(int(lags), max(0, n // 5))))
    var = g0
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        g = float(np.dot(e[lag:], e[:-lag]) / n)
        var += 2.0 * w * g
    fallback = 0
    if (not np.isfinite(var)) or var <= 1e-18:
        var = g0
        fallback = 1
    se = math.sqrt(var / n) if var > 0 else float("nan")
    return mean, se, fallback


def t_of(mean: float, se: float, shift: float = 0.0) -> float:
    if not np.isfinite(se) or se <= 0 or not np.isfinite(mean):
        return float("nan")
    return (mean - shift) / se


def iid_se(x: np.ndarray) -> tuple[float, float]:
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 3:
        return float("nan"), float("nan")
    mean = float(x.mean())
    sd = float(x.std(ddof=1))
    se = sd / math.sqrt(n)
    return mean, se


def overlap_lags(idx: np.ndarray, h: int) -> int:
    if idx.size < 5:
        return 0
    right = np.searchsorted(idx, idx + h, side="right")
    followers = right - np.arange(idx.size) - 1
    q = float(np.percentile(followers, 95))
    return int(max(0, math.ceil(q)))


def purge_mask(idx: np.ndarray, h: int) -> np.ndarray:
    keep = np.zeros(idx.size, dtype=bool)
    if idx.size == 0:
        return keep
    next_free = int(idx[0])
    for i, ix in enumerate(idx):
        if int(ix) >= next_free:
            keep[i] = True
            next_free = int(ix) + h
    return keep


def first_hit(mask: np.ndarray) -> np.ndarray:
    any_ = mask.any(axis=1)
    pos = mask.argmax(axis=1)
    return np.where(any_, pos, -1).astype(np.int16)


def welch(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float, float, int, int]:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    na, nb = int(a.size), int(b.size)
    if na < 3 or nb < 3:
        return (float("nan"),) * 4 + (na, nb)
    ma, mb = float(a.mean()), float(b.mean())
    va, vb = float(a.var(ddof=1)), float(b.var(ddof=1))
    se2 = va / na + vb / nb
    if se2 <= 0:
        return float("nan"), float("nan"), ma, mb, na, nb
    t = (ma - mb) / math.sqrt(se2)
    df = se2 ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    return t, df, ma, mb, na, nb


def pct_table(x: np.ndarray) -> dict:
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    qs = [10, 25, 50, 75, 90, 95, 99]
    out = {"n": int(x.size), "mean": float(x.mean()) if x.size else float("nan")}
    if x.size == 0:
        for q in qs:
            out[f"p{q}"] = float("nan")
        return out
    vals = np.percentile(x, qs)
    for q, v in zip(qs, vals):
        out[f"p{q}"] = float(v)
    return out


def funding_paid(idx: np.ndarray, side: np.ndarray, h: int, open_ms: np.ndarray,
                 fund_ms: np.ndarray, fund_rate: np.ndarray) -> np.ndarray:
    """Signed funding paid over (entry_close, entry_close + h bars], in return units.

    Positive means the side pays. Long pays when the funding rate is positive.
    """
    entry_close = open_ms[idx] + BAR_MS
    end = entry_close + h * BAR_MS
    left = np.searchsorted(fund_ms, entry_close, side="right")
    right = np.searchsorted(fund_ms, end, side="right")
    count = right - left
    paid = np.zeros(idx.size, dtype=np.float64)
    one = count == 1
    if np.any(one):
        paid[one] = side[one] * fund_rate[left[one]]
    multi = np.flatnonzero(count > 1)
    for j in multi:
        paid[j] = side[j] * float(fund_rate[left[j]: right[j]].sum())
    return paid


def unit_tests() -> None:
    assert abs(LONG_LIQ - (0.196 / 0.996)) < 1e-15
    assert abs(SHORT_LIQ - (0.196 / 1.004)) < 1e-15
    assert abs(bp(RT_TAKER) - 10.0) < 1e-12
    assert abs(bp(RT_MAKER) - 4.0) < 1e-12
    assert abs(bp(README_BLEND_ONE_WAY) - 2.4) < 1e-12
    assert abs(bp(RT_README_BLEND) - 4.8) < 1e-12

    x = np.full(40, 2.0)
    x[0] = 0.0
    w = wilder_smooth(x, 14)
    assert abs(w[14] - 2.0) < 1e-12
    assert abs(w[30] - 2.0) < 1e-12

    step = np.array([0, 1, 1, 1, 0, 1], dtype=np.int64)
    ok = window_ok(step, 2)
    assert ok.tolist() == [True, True, False, False, False, False]

    # Barrier toy: 1 entry, atr=1, entry close=100, 24 forward bars.
    # Bar +1 is the only interesting bar; the rest sit at 100.
    close = np.full(30, 100.0)
    high = np.full(30, 100.0)
    low = np.full(30, 100.0)
    # case stop only, placed at index 5 so offsets land on index 6
    low[6] = 97.0
    high[6] = 101.0
    flags = _barrier_one(close, high, low, idx=5, side=1, atr=1.0)
    assert bool(flags["stop15"]) and not bool(flags["target15"]) and not bool(flags["ambig15"])
    assert abs(flags["R15"] + 1.0) < 1e-12

    low[6] = 99.0
    high[6] = 104.0
    flags = _barrier_one(close, high, low, idx=5, side=1, atr=1.0)
    assert bool(flags["target15"]) and bool(flags["target20"])
    assert abs(flags["R15"] - 1.5) < 1e-12 and abs(flags["R20"] - 2.0) < 1e-12

    low[6] = 97.0
    high[6] = 104.0
    flags = _barrier_one(close, high, low, idx=5, side=1, atr=1.0)
    assert bool(flags["ambig15"]) and not bool(flags["target15"])
    assert abs(flags["R15"] + 1.0) < 1e-12

    low[:] = 99.5
    high[:] = 101.0
    close[:] = 100.0
    close[29] = 101.0
    # entry index must be 5, horizon bars 6..29 = 24 bars, last close is close[29]
    flags = _barrier_one(close, high, low, idx=5, side=1, atr=1.0)
    assert bool(flags["neither15"])
    assert abs(flags["R15"] - 0.5) < 1e-12  # (101-100)/(2*1)

    # scale-out: bar+1 hits +3 ATR and does not tag entry; bar+2 tags entry
    close[:] = 100.0
    high[:] = 100.2
    low[:] = 100.1
    high[6] = 103.2
    low[6] = 100.05
    low[7] = 100.0
    high[7] = 100.2
    flags = _barrier_one(close, high, low, idx=5, side=1, atr=1.0)
    assert bool(flags["target15"])
    assert abs(flags["Rscale"] - 0.75) < 1e-12

    print("unit_tests OK", flush=True)


def _barrier_one(close, high, low, idx, side, atr) -> dict:
    atr_series = np.full(close.shape[0], atr, dtype=np.float64)
    out = geometry_arrays(
        close, high, low,
        np.array([idx], dtype=np.int64),
        np.array([side], dtype=np.int8),
        atr_series,
    )
    return {k: (out[k][0] if isinstance(out[k], np.ndarray) else out[k]) for k in out}


def geometry_arrays(close, high, low, idx, side, atr) -> dict:
    """First-passage geometry for each entry. idx must have 24 bars of room."""
    n = idx.size
    R15 = np.empty(n, dtype=np.float64)
    R20 = np.empty(n, dtype=np.float64)
    Rscale = np.empty(n, dtype=np.float64)
    R15_opt = np.empty(n, dtype=np.float64)
    target15 = np.zeros(n, dtype=bool)
    target20 = np.zeros(n, dtype=bool)
    stop15 = np.zeros(n, dtype=bool)
    stop20 = np.zeros(n, dtype=bool)
    neither15 = np.zeros(n, dtype=bool)
    neither20 = np.zeros(n, dtype=bool)
    ambig15 = np.zeros(n, dtype=bool)
    ambig20 = np.zeros(n, dtype=bool)
    exit_bar = np.empty(n, dtype=np.int16)  # 1..24, for the scale-out / 1.5R race
    offsets = np.arange(1, 25, dtype=np.int64)
    chunk = 20000
    for a0 in range(0, n, chunk):
        a1 = min(a0 + chunk, n)
        ix = idx[a0:a1]
        hh = high[ix[:, None] + offsets]
        ll = low[ix[:, None] + offsets]
        p = close[ix][:, None]
        a = atr[ix][:, None]
        s = side[a0:a1].astype(np.float64)[:, None]
        adv = np.where(s > 0, p - ll, hh - p)
        fav = np.where(s > 0, hh - p, p - ll)
        stop_hit = adv >= (2.0 * a)
        tp15 = fav >= (3.0 * a)
        tp20 = fav >= (4.0 * a)
        be_hit = adv >= 0.0
        f_stop = first_hit(stop_hit)
        f_15 = first_hit(tp15)
        f_20 = first_hit(tp20)
        mtm = s[:, 0] * (close[ix + 24] - close[ix]) / (2.0 * atr[ix])

        def race(f_tgt, tgt_R):
            t_first = (f_tgt >= 0) & ((f_stop < 0) | (f_tgt < f_stop))
            s_first = (f_stop >= 0) & ((f_tgt < 0) | (f_stop <= f_tgt))
            neither = (f_tgt < 0) & (f_stop < 0)
            amb = (f_tgt >= 0) & (f_stop >= 0) & (f_tgt == f_stop)
            R = np.zeros(ix.size, dtype=np.float64)
            R[t_first] = tgt_R
            R[s_first] = -1.0
            R[neither] = mtm[neither]
            # optimistic tie: target wins same-bar ties
            t_opt = (f_tgt >= 0) & ((f_stop < 0) | (f_tgt <= f_stop))
            s_opt = (f_stop >= 0) & ((f_tgt < 0) | (f_stop < f_tgt))
            Ro = np.zeros(ix.size, dtype=np.float64)
            Ro[t_opt] = tgt_R
            Ro[s_opt] = -1.0
            Ro[~(t_opt | s_opt)] = mtm[~(t_opt | s_opt)]
            return R, Ro, t_first, s_first, neither, amb

        r15, r15o, t15, s15, n15, a15 = race(f_15, 1.5)
        r20, _, t20, s20, n20, a20 = race(f_20, 2.0)

        # Scale-out: 50% at 1.5R, stop to break-even, 50% at 2R.
        # Same-bar stop vs TP1 = full stop. Runner is judged on later bars only.
        full_stop = s15
        took = t15
        timeout_full = n15
        ks = np.arange(24, dtype=np.int16)[None, :]
        elig = (ks > f_15[:, None]) & took[:, None]
        f_run_tp = first_hit(elig & tp20)
        f_run_be = first_hit(elig & be_hit)
        run_tp = took & (f_run_tp >= 0) & ((f_run_be < 0) | (f_run_tp < f_run_be))
        run_be = took & (f_run_be >= 0) & ((f_run_tp < 0) | (f_run_be <= f_run_tp))
        run_to = took & ~run_tp & ~run_be
        rs = np.zeros(ix.size, dtype=np.float64)
        rs[full_stop] = -1.0
        rs[timeout_full] = mtm[timeout_full]
        rs[run_tp] = 0.5 * 1.5 + 0.5 * 2.0
        rs[run_be] = 0.5 * 1.5
        rs[run_to] = 0.5 * 1.5 + 0.5 * mtm[run_to]

        # Exit bar (1..24) for the conservative 1.5R race, used only as a diagnostic.
        eb = np.full(ix.size, 24, dtype=np.int16)
        eb[t15] = (f_15[t15] + 1).astype(np.int16)
        eb[s15] = (f_stop[s15] + 1).astype(np.int16)

        R15[a0:a1] = r15
        R20[a0:a1] = r20
        Rscale[a0:a1] = rs
        R15_opt[a0:a1] = r15o
        target15[a0:a1] = t15
        target20[a0:a1] = t20
        stop15[a0:a1] = s15
        stop20[a0:a1] = s20
        neither15[a0:a1] = n15
        neither20[a0:a1] = n20
        ambig15[a0:a1] = a15
        ambig20[a0:a1] = a20
        exit_bar[a0:a1] = eb
    return {
        "R15": R15,
        "R20": R20,
        "Rscale": Rscale,
        "R15_opt": R15_opt,
        "target15": target15,
        "target20": target20,
        "stop15": stop15,
        "stop20": stop20,
        "neither15": neither15,
        "neither20": neither20,
        "ambig15": ambig15,
        "ambig20": ambig20,
        "exit_bar": exit_bar,
    }


def json_ready(obj):
    if isinstance(obj, dict):
        return {str(k): json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_ready(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return json_ready(obj.tolist())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        if not math.isfinite(v):
            return None
        return v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def summarize_forward(name: str, side_name: str, h: int, ret: np.ndarray,
                      ret_open: np.ndarray, idx: np.ndarray, funding: np.ndarray,
                      n_slice_entries: int) -> dict:
    mean, se, fb = nw_mean_se(ret, overlap_lags(idx, h))
    row = {
        "slice": name,
        "side": side_name,
        "horizon_bars": h,
        "horizon": HORIZON_LABEL[h],
        "n_entries_in_slice": int(n_slice_entries),
        "n": int(np.isfinite(ret).sum()),
        "mean_gross_bp": bp(mean),
        "se_nw_gross_bp": bp(se),
        "nw_lags": int(overlap_lags(idx, h)),
        "nw_fallback_iid": int(fb),
        "nw_t_gross": t_of(mean, se, 0.0),
        "hit_rate_gross": float(np.mean(ret > 0)) if ret.size else float("nan"),
        "mean_gross_nextopen_bp": bp(float(np.nanmean(ret_open))) if ret_open.size else float("nan"),
        "hit_rate_nextopen": float(np.mean(ret_open > 0)) if ret_open.size else float("nan"),
        "mean_funding_paid_bp": bp(float(np.nanmean(funding))) if funding.size else float("nan"),
    }
    for label, cost in (("rt10", RT_TAKER), ("rt4", RT_MAKER),
                        ("rt4_8", RT_README_BLEND), ("rt7", RT_MAKER_IN_TAKER_OUT)):
        row[f"mean_net_{label}_bp"] = bp(mean - cost)
        row[f"nw_t_net_{label}"] = t_of(mean, se, cost)
        row[f"hit_rate_net_{label}"] = float(np.mean(ret > cost)) if ret.size else float("nan")
    row["mean_net_rt10_plus_funding_bp"] = bp(mean - RT_TAKER - float(np.nanmean(funding)))
    keep = purge_mask(idx, h)
    if keep.any():
        pm, pse = iid_se(ret[keep])
        row["purged_n"] = int(keep.sum())
        row["purged_mean_gross_bp"] = bp(pm)
        row["purged_t_gross"] = t_of(pm, pse, 0.0)
        row["purged_t_net_rt10"] = t_of(pm, pse, RT_TAKER)
        row["purged_t_net_rt4"] = t_of(pm, pse, RT_MAKER)
        row["purged_mean_net_rt10_bp"] = bp(pm - RT_TAKER)
    else:
        row["purged_n"] = 0
        row["purged_mean_gross_bp"] = float("nan")
        row["purged_t_gross"] = float("nan")
        row["purged_t_net_rt10"] = float("nan")
        row["purged_t_net_rt4"] = float("nan")
        row["purged_mean_net_rt10_bp"] = float("nan")
    return row


def summarize_R(name: str, side_name: str, trade: str, R: np.ndarray,
                R_opt: np.ndarray | None, target: np.ndarray, stop: np.ndarray,
                neither: np.ndarray, ambig: np.ndarray, stop_bp: np.ndarray,
                idx: np.ndarray) -> dict:
    cost10 = 10.0 / stop_bp
    cost4 = 4.0 / stop_bp
    net10 = R - cost10
    net4 = R - cost4
    mean, se, fb = nw_mean_se(net10, overlap_lags(idx, 24))
    # se is of net10; gross mean R has the same se
    mean_R = float(np.mean(R))
    # recompute se on R itself for the gross t; numerical identity holds
    _, se_R, _ = nw_mean_se(R, overlap_lags(idx, 24))
    keep = purge_mask(idx, 24)
    if keep.any():
        pm, pse = iid_se(net10[keep])
        purged_n = int(keep.sum())
        purged_t = t_of(pm, pse, 0.0)
        purged_mean = pm
    else:
        purged_n, purged_t, purged_mean = 0, float("nan"), float("nan")
    row = {
        "slice": name,
        "side": side_name,
        "trade": trade,
        "n": int(R.size),
        "target_first_n": int(target.sum()),
        "stop_first_n": int(stop.sum()),
        "neither_n": int(neither.sum()),
        "ambiguous_same_bar_n": int(ambig.sum()),
        "target_first_rate": float(target.mean()),
        "stop_first_rate": float(stop.mean()),
        "neither_rate": float(neither.mean()),
        "win_rate_gross_R_gt_0": float(np.mean(R > 0)),
        "win_rate_net_rt10": float(np.mean(net10 > 0)),
        "win_rate_net_rt4": float(np.mean(net4 > 0)),
        "mean_gross_R": mean_R,
        "median_gross_R": float(np.median(R)),
        "mean_net_R_rt10": float(np.mean(net10)),
        "median_net_R_rt10": float(np.median(net10)),
        "mean_net_R_rt4": float(np.mean(net4)),
        "median_net_R_rt4": float(np.median(net4)),
        "nw_t_net_rt10": t_of(mean, se, 0.0),
        "nw_t_gross_R": t_of(mean_R, se_R, 0.0),
        "nw_fallback_iid": int(fb),
        "nw_lags": int(overlap_lags(idx, 24)),
        "purged_n": purged_n,
        "purged_mean_net_R_rt10": purged_mean,
        "purged_t_net_rt10": purged_t,
        "median_stop_bp": float(np.median(stop_bp)),
        "frac_stop_bp_lt_10": float(np.mean(stop_bp < 10.0)),
        "frac_stop_bp_lt_4": float(np.mean(stop_bp < 4.0)),
        "frac_stop_bp_lt_4_8": float(np.mean(stop_bp < 4.8)),
        "median_cost_R_rt10": float(np.median(cost10)),
    }
    if R_opt is not None:
        net_opt = R_opt - cost10
        row["optimistic_tie_mean_net_R_rt10"] = float(np.mean(net_opt))
        row["optimistic_tie_win_rate_net_rt10"] = float(np.mean(net_opt > 0))
        row["optimistic_tie_target_rate"] = float("nan")
    else:
        row["optimistic_tie_mean_net_R_rt10"] = float("nan")
        row["optimistic_tie_win_rate_net_rt10"] = float("nan")
        row["optimistic_tie_target_rate"] = float("nan")
    return row


def main() -> None:
    t0 = time.time()
    unit_tests()
    print("loading trade bars", flush=True)
    df = pd.read_csv(
        TRADE_PATH,
        usecols=["open_time_ms", "open_time_utc", "open", "high", "low", "close",
                 "volume", "quote_volume"],
    )
    df["open_time_ms"] = df["open_time_ms"].astype(np.int64)
    df = df.sort_values("open_time_ms").reset_index(drop=True)
    n = len(df)
    open_ms = df["open_time_ms"].to_numpy(np.int64)
    ot = pd.DatetimeIndex(pd.to_datetime(df["open_time_utc"], utc=True))
    o = df["open"].to_numpy(np.float64)
    h = df["high"].to_numpy(np.float64)
    lo = df["low"].to_numpy(np.float64)
    c = df["close"].to_numpy(np.float64)
    vol = df["volume"].to_numpy(np.float64)
    qvol = df["quote_volume"].to_numpy(np.float64)
    hours = ot.hour.to_numpy()
    years = ot.year.to_numpy()
    minutes = ot.minute.to_numpy()
    dates = ot.floor("D").to_numpy()

    step = np.zeros(n, dtype=np.int64)
    step[1:] = (np.diff(open_ms) == BAR_MS).astype(np.int64)
    gap_at = np.flatnonzero(step[1:] == 0) + 1  # bar index where the gap arrives
    ok_h = {hz: window_ok(step, hz) for hz in HORIZONS}

    print("loading mark and funding", flush=True)
    mk = pd.read_csv(MARK_PATH, usecols=["open_time_ms", "high", "low", "close"])
    mk["open_time_ms"] = mk["open_time_ms"].astype(np.int64)
    n_mark_dup = int(mk["open_time_ms"].duplicated().sum())
    mk = mk.drop_duplicates("open_time_ms", keep="last")
    merged = df[["open_time_ms"]].merge(mk, on="open_time_ms", how="left", sort=False)
    if len(merged) != n:
        raise RuntimeError(f"mark merge changed length {len(merged)} != {n}")
    mark_h = merged["high"].to_numpy(np.float64)
    mark_l = merged["low"].to_numpy(np.float64)
    mark_c = merged["close"].to_numpy(np.float64)
    del merged, mk

    fund = pd.read_csv(FUND_PATH, usecols=["funding_time_ms", "funding_rate"])
    fund = fund.dropna(subset=["funding_time_ms", "funding_rate"])
    raw_ms = fund["funding_time_ms"].to_numpy(np.int64)
    floored = (raw_ms // 3_600_000) * 3_600_000
    fund_hours = (floored // 3_600_000) % 24
    bad_hours = int(np.sum(~np.isin(fund_hours, [0, 8, 16])))
    fund_df = pd.DataFrame({"ms": floored, "rate": fund["funding_rate"].to_numpy(np.float64)})
    n_fund_dup = int(fund_df["ms"].duplicated().sum())
    fund_df = fund_df.groupby("ms", as_index=False)["rate"].mean().sort_values("ms")
    fund_ms = fund_df["ms"].to_numpy(np.int64)
    fund_rate = fund_df["rate"].to_numpy(np.float64)

    print("indicators", flush=True)
    delta = np.empty(n, dtype=np.float64)
    delta[0] = 0.0
    delta[1:] = c[1:] - c[:-1]
    gain = np.clip(delta, 0.0, None)
    loss = np.clip(-delta, 0.0, None)
    ag = wilder_smooth(gain, 14)
    al = wilder_smooth(loss, 14)
    rsi = np.full(n, np.nan)
    both0 = np.isfinite(ag) & np.isfinite(al) & (ag <= 0) & (al <= 0)
    up = np.isfinite(ag) & np.isfinite(al) & (al <= 0) & (ag > 0)
    down = np.isfinite(ag) & np.isfinite(al) & (ag <= 0) & (al > 0)
    mid = np.isfinite(ag) & np.isfinite(al) & (ag > 0) & (al > 0)
    rsi[both0] = 50.0
    rsi[up] = 100.0
    rsi[down] = 0.0
    rsi[mid] = 100.0 - 100.0 / (1.0 + ag[mid] / al[mid])

    # SMA RSI, the embedded code's definition, for the bug check only.
    gain_s = pd.Series(gain)
    loss_s = pd.Series(loss)
    ag_sma = gain_s.rolling(14).mean().to_numpy()
    al_sma = loss_s.rolling(14).mean().to_numpy()
    rsi_sma = np.full(n, np.nan)
    both0 = np.isfinite(ag_sma) & np.isfinite(al_sma) & (al_sma == 0) & (ag_sma == 0)
    up = np.isfinite(ag_sma) & np.isfinite(al_sma) & (al_sma == 0) & (ag_sma > 0)
    down = np.isfinite(ag_sma) & np.isfinite(al_sma) & (ag_sma == 0) & (al_sma > 0)
    mid = np.isfinite(ag_sma) & np.isfinite(al_sma) & (al_sma > 0)
    rsi_sma[both0] = 50.0
    rsi_sma[up] = 100.0
    rsi_sma[down] = 0.0
    rsi_sma[mid] = 100.0 - 100.0 / (1.0 + ag_sma[mid] / al_sma[mid])

    close_s = pd.Series(c)
    ema20 = close_s.ewm(span=20, adjust=False).mean().to_numpy()
    ema50 = close_s.ewm(span=50, adjust=False).mean().to_numpy()
    ema12 = close_s.ewm(span=12, adjust=False).mean().to_numpy()
    ema26 = close_s.ewm(span=26, adjust=False).mean().to_numpy()
    macd = ema12 - ema26
    macd_sig = pd.Series(macd).ewm(span=9, adjust=False).mean().to_numpy()
    hist = macd - macd_sig

    prev_c = np.empty(n, dtype=np.float64)
    prev_c[0] = c[0]
    prev_c[1:] = c[:-1]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - prev_c), np.abs(lo - prev_c)))
    tr[0] = h[0] - lo[0]
    atr = wilder_smooth(tr, 14)
    # SMA ATR, embedded code, bug check only (not used for the trade geometry).
    atr_sma = pd.Series(tr).rolling(14).mean().to_numpy()

    tp = (h + lo + c) / 3.0
    pv = tp * vol
    day = pd.Series(dates)
    cum_pv = pd.Series(pv).groupby(day, sort=False).cumsum().to_numpy()
    cum_vol = pd.Series(vol).groupby(day, sort=False).cumsum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = np.where(cum_vol > 0, cum_pv / cum_vol, np.nan)
        total_vol = np.cumsum(vol)
        vwap_bug = np.where(total_vol > 0, np.cumsum(pv) / total_vol, np.nan)

    base_ok = (
        (np.arange(n) >= WARMUP)
        & np.isfinite(rsi) & np.isfinite(ema20) & np.isfinite(ema50)
        & np.isfinite(macd_sig) & np.isfinite(atr) & (atr > 0)
        & np.isfinite(c) & (c > 0) & (vol > 0)
    )

    def make_signal(vw, rsi_arr):
        long_m = (
            base_ok & np.isfinite(vw) & (c > ema20) & (ema20 > ema50) & (c > vw)
            & (macd > macd_sig) & (hist > 0) & (rsi_arr >= 45.0) & (rsi_arr <= 65.0)
        )
        short_m = (
            base_ok & np.isfinite(vw) & (c < ema20) & (ema20 < ema50) & (c < vw)
            & (macd < macd_sig) & (hist < 0) & (rsi_arr >= 35.0) & (rsi_arr <= 55.0)
        )
        both = long_m & short_m
        sig = np.zeros(n, dtype=np.int8)
        sig[long_m & ~both] = 1
        sig[short_m & ~both] = -1
        return sig, int(both.sum())

    sig, n_both = make_signal(vwap, rsi)
    sig_bug_vwap, _ = make_signal(vwap_bug, rsi)
    sig_code, _ = make_signal(vwap_bug, rsi_sma)
    hist_disagree = int(np.sum(base_ok & ((macd > macd_sig) != (hist > 0))))

    prev = np.zeros(n, dtype=np.int8)
    prev[1:] = sig[:-1]
    fresh = (sig != 0) & (prev == 0)
    flips = (sig != 0) & (prev != 0) & (sig != prev)
    idx_all = np.flatnonzero(fresh)
    side_all = sig[idx_all]
    idx_flip = np.flatnonzero((sig != 0) & (sig != prev))

    session = (hours >= 12) & (hours < 20)

    # ----- market re-verification and move distribution -----
    print("move distribution", flush=True)
    r1 = np.full(n, np.nan)
    r1[1:] = c[1:] / c[:-1] - 1.0
    contig = step == 1
    r_contig = r1[contig]
    # lag-1 autocorr where both r[i] and r[i-1] are real 5m steps
    both_steps = np.zeros(n, dtype=bool)
    both_steps[2:] = (step[1:-1] == 1) & (step[2:] == 1)
    ac = float(np.corrcoef(r1[both_steps], r1[np.flatnonzero(both_steps) - 1])[0, 1])

    move_rows = []
    for hz in HORIZONS:
        rr = np.abs(c[np.flatnonzero(ok_h[hz]) + hz] / c[np.flatnonzero(ok_h[hz])] - 1.0) * 1e4
        stats = pct_table(rr)
        row = {"sample": "rolling_contiguous", "horizon_bars": hz, "horizon": HORIZON_LABEL[hz]}
        row.update(stats)
        for thr, key in ((4.0, "frac_gt_4bp"), (4.8, "frac_gt_4_8bp"),
                         (8.0, "frac_gt_8bp"), (10.0, "frac_gt_10bp")):
            row[key] = float(np.mean(rr > thr)) if rr.size else float("nan")
        move_rows.append(row)

    # Clock-hour close-to-close: bar at :55 versus the :55 twelve bars earlier.
    hour_ix = np.flatnonzero((minutes == 55) & (np.arange(n) >= 12))
    hour_ok = ok_h[12][hour_ix - 12]
    hour_ix = hour_ix[hour_ok]
    hour_abs = np.abs(c[hour_ix] / c[hour_ix - 12] - 1.0) * 1e4
    hour_stats = pct_table(hour_abs)
    hour_row = {"sample": "clock_1h_close", "horizon_bars": 12, "horizon": "1h_clock"}
    hour_row.update(hour_stats)
    for thr, key in ((4.0, "frac_gt_4bp"), (4.8, "frac_gt_4_8bp"),
                     (8.0, "frac_gt_8bp"), (10.0, "frac_gt_10bp")):
        hour_row[key] = float(np.mean(hour_abs > thr)) if hour_abs.size else float("nan")
    move_rows.append(hour_row)

    valid_atr = base_ok & np.isfinite(atr) & (atr > 0)
    atr_bp = np.full(n, np.nan)
    atr_bp[valid_atr] = atr[valid_atr] / c[valid_atr] * 1e4
    stop_bp_bar = 2.0 * atr_bp
    fresh_stop_bp = stop_bp_bar[idx_all]

    def atr_row(scope: str, stop_bp_arr: np.ndarray, atr_bp_arr: np.ndarray) -> dict:
        st = stop_bp_arr[np.isfinite(stop_bp_arr)]
        aa = atr_bp_arr[np.isfinite(atr_bp_arr)]
        return {
            "scope": scope,
            "n": int(st.size),
            "atr_p50_bp": float(np.median(aa)) if aa.size else float("nan"),
            "atr_p25_bp": float(np.percentile(aa, 25)) if aa.size else float("nan"),
            "atr_p75_bp": float(np.percentile(aa, 75)) if aa.size else float("nan"),
            "stop_p25_bp": float(np.percentile(st, 25)) if st.size else float("nan"),
            "stop_p50_bp": float(np.median(st)) if st.size else float("nan"),
            "stop_p75_bp": float(np.percentile(st, 75)) if st.size else float("nan"),
            "stop_p90_bp": float(np.percentile(st, 90)) if st.size else float("nan"),
            "frac_stop_lt_4bp": float(np.mean(st < 4.0)),
            "frac_stop_lt_4_8bp": float(np.mean(st < 4.8)),
            "frac_stop_lt_8bp": float(np.mean(st < 8.0)),
            "frac_stop_lt_10bp": float(np.mean(st < 10.0)),
            "frac_stop_in_40_to_80bp": float(np.mean((st >= 40.0) & (st <= 80.0))),
            "equity_risk_at_0_75x": float(0.75 * np.median(st) / 1e4) if st.size else float("nan"),
            "equity_risk_at_5x": float(5.0 * np.median(st) / 1e4) if st.size else float("nan"),
        }

    atr_rows = [
        atr_row("valid_bars_after_warmup", stop_bp_bar[valid_atr], atr_bp[valid_atr]),
        atr_row("fresh_entries", fresh_stop_bp, fresh_stop_bp / 2.0),
    ]

    # close-to-next-open gap, contiguous only
    gap_bp = np.abs(o[1:] / c[:-1] - 1.0) * 1e4
    gap_bp = gap_bp[step[1:] == 1]
    tick_bp = 0.1 / c[valid_atr] * 1e4
    step_notional = 0.001 * c[valid_atr]

    # ----- signals -----
    print("signal counts", flush=True)
    eval_bars = np.arange(n) >= WARMUP
    n_eval = int(eval_bars.sum())

    def signal_record(variant: str, s_arr: np.ndarray) -> dict:
        long_m = s_arr == 1
        short_m = s_arr == -1
        pv_ = np.zeros(n, dtype=np.int8)
        pv_[1:] = s_arr[:-1]
        fr = (s_arr != 0) & (pv_ == 0)
        st_l, len_l = run_lengths(long_m)
        st_s, len_s = run_lengths(short_m)
        return {
            "variant": variant,
            "n_eval_bars": n_eval,
            "n_long_bars": int(long_m.sum()),
            "n_short_bars": int(short_m.sum()),
            "frac_long_bars": float(long_m[eval_bars].mean()) if n_eval else float("nan"),
            "frac_short_bars": float(short_m[eval_bars].mean()) if n_eval else float("nan"),
            "frac_either_bars": float(((s_arr != 0) & eval_bars).sum() / n_eval),
            "n_fresh_long": int(((s_arr == 1) & (pv_ == 0)).sum()),
            "n_fresh_short": int(((s_arr == -1) & (pv_ == 0)).sum()),
            "n_fresh": int(fr.sum()),
            "median_run_long": float(np.median(len_l)) if len_l.size else float("nan"),
            "median_run_short": float(np.median(len_s)) if len_s.size else float("nan"),
            "mean_run_long": float(len_l.mean()) if len_l.size else float("nan"),
            "mean_run_short": float(len_s.mean()) if len_s.size else float("nan"),
            "n_bars_signal_differs_from_main": int(np.sum((s_arr != sig) & eval_bars)),
        }

    sig_rows = [
        signal_record("daily_vwap_wilder_rsi", sig),
        signal_record("cumsum_vwap_wilder_rsi", sig_bug_vwap),
        signal_record("cumsum_vwap_sma_rsi_code", sig_code),
    ]

    def daily_entry_stats(ix: np.ndarray, day_mask: np.ndarray) -> tuple[int, int, float, float]:
        day_vals = dates[day_mask]
        all_days = np.unique(day_vals)
        n_days = int(all_days.size)
        if ix.size == 0 or n_days == 0:
            return 0, n_days, 0.0, 0.0
        pos = np.searchsorted(all_days, dates[ix])
        counts = np.bincount(pos, minlength=n_days)
        return int(ix.size), n_days, float(ix.size / n_days), float(np.median(counts))

    st_l, len_l = run_lengths(sig == 1)
    st_s, len_s = run_lengths(sig == -1)
    year_rows = []
    year_list = list(range(int(years.min()), int(years.max()) + 1))
    for y in year_list:
        in_y = years == y
        # evaluation days only (after warmup) so 2019's first 200 bars are not a full day
        in_y_eval = in_y & eval_bars
        ix = idx_all[years[idx_all] == y]
        n_fr, n_days, per_day, med_day = daily_entry_stats(ix, in_y_eval if in_y_eval.any() else in_y)
        long_runs = len_l[years[st_l] == y] if st_l.size else np.array([])
        short_runs = len_s[years[st_s] == y] if st_s.size else np.array([])
        n_long = int(((sig == 1) & in_y).sum())
        n_short = int(((sig == -1) & in_y).sum())
        n_bars_y = int(in_y_eval.sum())
        year_rows.append({
            "year": y,
            "n_eval_bars": n_bars_y,
            "n_days": n_days,
            "n_long_bars": n_long,
            "n_short_bars": n_short,
            "frac_long": float(n_long / n_bars_y) if n_bars_y else float("nan"),
            "frac_short": float(n_short / n_bars_y) if n_bars_y else float("nan"),
            "n_fresh_long": int((side_all[years[idx_all] == y] == 1).sum()) if ix.size else 0,
            "n_fresh_short": int((side_all[years[idx_all] == y] == -1).sum()) if ix.size else 0,
            "n_fresh": n_fr,
            "fresh_per_day": per_day,
            "median_daily_fresh": med_day,
            "median_run_long": float(np.median(long_runs)) if long_runs.size else float("nan"),
            "median_run_short": float(np.median(short_runs)) if short_runs.size else float("nan"),
            "mean_run_long": float(long_runs.mean()) if long_runs.size else float("nan"),
            "mean_run_short": float(short_runs.mean()) if short_runs.size else float("nan"),
            "n_fresh_in_session": int(session[ix].sum()) if ix.size else 0,
            "frac_fresh_in_session": float(session[ix].mean()) if ix.size else float("nan"),
        })
    # full sample row
    n_fr, n_days, per_day, med_day = daily_entry_stats(idx_all, eval_bars)
    year_rows.append({
        "year": "full",
        "n_eval_bars": n_eval,
        "n_days": n_days,
        "n_long_bars": int((sig == 1).sum()),
        "n_short_bars": int((sig == -1).sum()),
        "frac_long": float((sig[eval_bars] == 1).mean()),
        "frac_short": float((sig[eval_bars] == -1).mean()),
        "n_fresh_long": int((side_all == 1).sum()),
        "n_fresh_short": int((side_all == -1).sum()),
        "n_fresh": n_fr,
        "fresh_per_day": per_day,
        "median_daily_fresh": med_day,
        "median_run_long": float(np.median(len_l)) if len_l.size else float("nan"),
        "median_run_short": float(np.median(len_s)) if len_s.size else float("nan"),
        "mean_run_long": float(len_l.mean()) if len_l.size else float("nan"),
        "mean_run_short": float(len_s.mean()) if len_s.size else float("nan"),
        "n_fresh_in_session": int(session[idx_all].sum()),
        "frac_fresh_in_session": float(session[idx_all].mean()) if idx_all.size else float("nan"),
    })

    # ----- session tests on |moves| and volume -----
    print("session tests", flush=True)
    session_rows = []

    def add_session_abs(label: str, values_bp: np.ndarray, start_idx: np.ndarray):
        ses = session[start_idx]
        a = values_bp[ses]
        b = values_bp[~ses]
        t, df_, ma, mb, na, nb = welch(a, b)
        session_rows.append({
            "metric": label, "group": "session_12_20", "n": int(a.size),
            "median_bp": float(np.median(a)) if a.size else float("nan"),
            "mean_bp": float(np.mean(a)) if a.size else float("nan"),
            "welch_t_session_minus_rest": float("nan"), "welch_df": float("nan"),
        })
        session_rows.append({
            "metric": label, "group": "rest", "n": int(b.size),
            "median_bp": float(np.median(b)) if b.size else float("nan"),
            "mean_bp": float(np.mean(b)) if b.size else float("nan"),
            "welch_t_session_minus_rest": float("nan"), "welch_df": float("nan"),
        })
        session_rows.append({
            "metric": label, "group": "session_minus_rest", "n": int(a.size + b.size),
            "median_bp": (float(np.median(a) - np.median(b)) if a.size and b.size else float("nan")),
            "mean_bp": (float(np.mean(a) - np.mean(b)) if a.size and b.size else float("nan")),
            "welch_t_session_minus_rest": t, "welch_df": df_,
        })

    for hz in (1, 3, 12, 24):
        ix = np.flatnonzero(ok_h[hz])
        vals = np.abs(c[ix + hz] / c[ix] - 1.0) * 1e4
        add_session_abs(f"abs_close_to_close_{HORIZON_LABEL[hz]}", vals, ix)

    # quote volume, all bars
    add_session_abs("quote_volume_usdt", qvol, np.arange(n))
    # signal rate
    for group_name, mask in (("session_12_20", session & eval_bars), ("rest", (~session) & eval_bars)):
        m = mask
        session_rows.append({
            "metric": "signal_bar_rate",
            "group": group_name,
            "n": int(m.sum()),
            "median_bp": float("nan"),
            "mean_bp": float((sig[m] != 0).mean()) if m.any() else float("nan"),
            "welch_t_session_minus_rest": float("nan"),
            "welch_df": float("nan"),
            "note": "mean_bp column holds the fraction of bars with a signal, not bp",
        })

    # ----- forward returns -----
    print(f"forward returns on {idx_all.size} fresh entries", flush=True)
    slices = {
        "full": np.ones(idx_all.size, dtype=bool),
        "y2020_2023": (years[idx_all] >= 2020) & (years[idx_all] <= 2023),
        "y2024_2026": (years[idx_all] >= 2024) & (years[idx_all] <= 2026),
        "session_12_20": session[idx_all],
        "session_rest": ~session[idx_all],
    }
    side_masks = {
        "all": np.ones(idx_all.size, dtype=bool),
        "long": side_all == 1,
        "short": side_all == -1,
    }
    fwd_rows = []
    # Cache per-horizon returns on the full fresh set, then subset.
    cached = {}
    for hz in HORIZONS:
        ok = ok_h[hz][idx_all]
        ret = np.full(idx_all.size, np.nan)
        ret_o = np.full(idx_all.size, np.nan)
        good = np.flatnonzero(ok)
        if good.size:
            gi = idx_all[good]
            gs = side_all[good].astype(np.float64)
            ret[good] = gs * (c[gi + hz] / c[gi] - 1.0)
            ret_o[good] = gs * (c[gi + hz] / o[gi + 1] - 1.0)
        fund_paid = np.full(idx_all.size, np.nan)
        if good.size:
            fund_paid[good] = funding_paid(idx_all[good], side_all[good].astype(np.float64),
                                           hz, open_ms, fund_ms, fund_rate)
        cached[hz] = (ret, ret_o, fund_paid, ok)

    for sl_name, sl_mask in slices.items():
        for side_name, side_mask in side_masks.items():
            # Session x side x year would explode; keep side splits on full and year slices,
            # and session slices at side=all only.
            if sl_name.startswith("session") and side_name != "all":
                continue
            if sl_name in ("y2020_2023", "y2024_2026") and side_name != "all":
                # still want side x period? useful and not that expensive. Include it.
                pass
            base = sl_mask & side_mask
            n_slice = int(base.sum())
            pos = np.flatnonzero(base)
            for hz in HORIZONS:
                ret, ret_o, fund_paid, ok = cached[hz]
                use = pos[ok[pos]]
                if use.size == 0:
                    continue
                row = summarize_forward(
                    sl_name, side_name, hz,
                    ret[use], ret_o[use], idx_all[use], fund_paid[use], n_slice,
                )
                fwd_rows.append(row)

    # flip-inclusive sensitivity, full sample, both sides, two horizons
    print("flip sensitivity", flush=True)
    prev_f = np.zeros(n, dtype=np.int8)
    prev_f[1:] = sig[:-1]
    idx_any = idx_flip
    side_any = sig[idx_any]
    flip_rows = []
    for hz in (3, 24):
        ok = ok_h[hz][idx_any]
        gi = idx_any[ok]
        gs = side_any[ok].astype(np.float64)
        if gi.size == 0:
            continue
        ret = gs * (c[gi + hz] / c[gi] - 1.0)
        ret_o = gs * (c[gi + hz] / o[gi + 1] - 1.0)
        paid = funding_paid(gi, gs, hz, open_ms, fund_ms, fund_rate)
        row = summarize_forward("full_including_flips", "all", hz, ret, ret_o, gi, paid, int(idx_any.size))
        row["n_direct_flips_in_sample"] = int(flips.sum())
        flip_rows.append(row)

    # ----- geometry -----
    print("stop/TP geometry", flush=True)
    ok24 = ok_h[24][idx_all]
    idx_g = idx_all[ok24]
    side_g = side_all[ok24]
    atr_g = atr[idx_g]
    stop_g = atr_g / c[idx_g] * 1e4 * 2.0
    geo = geometry_arrays(c, h, lo, idx_g, side_g, atr)
    geo_rows = []
    geo_slices = {
        "full": np.ones(idx_g.size, dtype=bool),
        "y2020_2023": (years[idx_g] >= 2020) & (years[idx_g] <= 2023),
        "y2024_2026": (years[idx_g] >= 2024) & (years[idx_g] <= 2026),
        "long": side_g == 1,
        "short": side_g == -1,
        "session_12_20": session[idx_g],
        "session_rest": ~session[idx_g],
    }
    trades = (
        ("race_1.5R", "R15", "R15_opt", "target15", "stop15", "neither15", "ambig15"),
        ("race_2R", "R20", None, "target20", "stop20", "neither20", "ambig20"),
        ("scaleout_50_1.5_then_2R", "Rscale", None, "target15", "stop15", "neither15", "ambig15"),
    )
    for sl_name, mask in geo_slices.items():
        if not mask.any():
            continue
        ix = idx_g[mask]
        stp = stop_g[mask]
        side_name = "long" if sl_name == "long" else "short" if sl_name == "short" else "all"
        slice_name = "full" if sl_name in ("long", "short") else sl_name
        for trade, rk, rok, tk, sk, nk, ak in trades:
            row = summarize_R(
                slice_name, side_name, trade,
                geo[rk][mask],
                geo[rok][mask] if rok else None,
                geo[tk][mask], geo[sk][mask], geo[nk][mask], geo[ak][mask],
                stp, ix,
            )
            if sl_name in ("long", "short"):
                row["slice"] = "full"
                row["side"] = sl_name
            geo_rows.append(row)

    # ----- liquidation -----
    print("liquidation check", flush=True)
    offsets = np.arange(1, 25, dtype=np.int64)
    # chunk to limit memory
    adv = np.full(idx_g.size, np.nan)
    mark_complete = np.zeros(idx_g.size, dtype=bool)
    trade_adv = np.full(idx_g.size, np.nan)
    chunk = 20000
    for a0 in range(0, idx_g.size, chunk):
        a1 = min(a0 + chunk, idx_g.size)
        ix = idx_g[a0:a1]
        mh = mark_h[ix[:, None] + offsets]
        ml = mark_l[ix[:, None] + offsets]
        complete = np.isfinite(mh).all(axis=1) & np.isfinite(ml).all(axis=1)
        mark_complete[a0:a1] = complete
        p = c[ix]
        s = side_g[a0:a1]
        # adverse mark move; incomplete stays nan
        max_adv = np.full(ix.size, np.nan)
        if complete.any():
            # compute only on complete rows
            min_l = np.full(ix.size, np.nan)
            max_h = np.full(ix.size, np.nan)
            min_l[complete] = ml[complete].min(axis=1)
            max_h[complete] = mh[complete].max(axis=1)
            max_adv = np.where(s == 1, (p - min_l) / p, (max_h - p) / p)
            max_adv[~complete] = np.nan
        adv[a0:a1] = max_adv
        th = h[ix[:, None] + offsets]
        tl = lo[ix[:, None] + offsets]
        trade_adv[a0:a1] = np.where(
            s == 1,
            (p - tl.min(axis=1)) / p,
            (th.max(axis=1) - p) / p,
        )

    comp = mark_complete & np.isfinite(adv)
    thresh = np.where(side_g == 1, LONG_LIQ, SHORT_LIQ)
    hit_exact = comp & (adv >= thresh)
    hit_197 = comp & (adv >= LIQ_19_7)
    # incomplete windows: trade-price proxy
    inc = ~mark_complete
    hit_trade_all = np.isfinite(trade_adv) & (trade_adv >= thresh)
    hit_trade_inc = inc & hit_trade_all

    def adv_stats(x):
        x = x[np.isfinite(x)]
        if x.size == 0:
            return {k: float("nan") for k in ("n", "median", "p99", "p999", "max")}
        return {
            "n": int(x.size),
            "median": float(np.median(x)),
            "p99": float(np.percentile(x, 99)),
            "p999": float(np.percentile(x, 99.9)),
            "max": float(np.max(x)),
        }

    adv_c = adv_stats(adv[comp])
    adv_t = adv_stats(trade_adv)
    # worst complete mark path
    if comp.any():
        # argmax over complete only
        tmp = np.where(comp, adv, -np.inf)
        w = int(np.argmax(tmp))
        worst = {
            "adverse": float(adv[w]),
            "side": int(side_g[w]),
            "entry_time_utc": str(ot[idx_g[w]]),
            "entry_close": float(c[idx_g[w]]),
            "threshold": float(thresh[w]),
        }
    else:
        worst = {}

    liq_rows = [{
        "n_fresh": int(idx_all.size),
        "n_with_24_contiguous_trade_bars": int(idx_g.size),
        "n_mark_complete": int(comp.sum()),
        "n_mark_incomplete": int((~mark_complete).sum()),
        "long_liq_distance": LONG_LIQ,
        "short_liq_distance": SHORT_LIQ,
        "n_hit_side_specific": int(hit_exact.sum()),
        "frac_hit_side_specific": float(hit_exact.sum() / comp.sum()) if comp.any() else float("nan"),
        "n_hit_long": int((hit_exact & (side_g == 1)).sum()),
        "n_hit_short": int((hit_exact & (side_g == -1)).sum()),
        "n_long_complete": int((comp & (side_g == 1)).sum()),
        "n_short_complete": int((comp & (side_g == -1)).sum()),
        "n_hit_ge_19_7pct": int(hit_197.sum()),
        "frac_hit_ge_19_7pct": float(hit_197.sum() / comp.sum()) if comp.any() else float("nan"),
        "mark_adv_median": adv_c["median"],
        "mark_adv_p99": adv_c["p99"],
        "mark_adv_p999": adv_c["p999"],
        "mark_adv_max": adv_c["max"],
        "trade_adv_median": adv_t["median"],
        "trade_adv_p99": adv_t["p99"],
        "trade_adv_p999": adv_t["p999"],
        "trade_adv_max": adv_t["max"],
        "n_trade_price_hit_side_specific": int(hit_trade_all.sum()),
        "n_incomplete_trade_proxy_hits": int(hit_trade_inc.sum()),
        "worst_entry_time_utc": worst.get("entry_time_utc"),
        "worst_side": worst.get("side"),
        "worst_adverse": worst.get("adverse"),
        "worst_threshold": worst.get("threshold"),
        "worst_entry_close": worst.get("entry_close"),
        "n_mark_dups_dropped": n_mark_dup,
    }]

    # ----- costs table -----
    cost_rows = [
        {"scenario": "vip0_taker_per_side", "per_side_bp": bp(TAKER_FEE), "round_trip_bp": bp(RT_TAKER),
         "notes": "verified VIP0 taker 0.050% each side; round trip is the realistic hurdle"},
        {"scenario": "readme_taker_per_side_4bp", "per_side_bp": bp(README_TAKER_FEE), "round_trip_bp": bp(RT_README_TAKER),
         "notes": "embedded code default taker_fee=0.0004; optimistic vs verified 5 bp"},
        {"scenario": "maker_maker", "per_side_bp": bp(MAKER_FEE), "round_trip_bp": bp(RT_MAKER),
         "notes": "VIP0 maker 0.020% each side; this is a fee, not a rebate"},
        {"scenario": "readme_80_20_blend", "per_side_bp": bp(README_BLEND_ONE_WAY), "round_trip_bp": bp(RT_README_BLEND),
         "notes": "0.8*2bp + 0.2*4bp per side, times two sides. Code then multiplies by leverage 5 in equity space"},
        {"scenario": "readme_blend_plus_1bp_slip_per_side", "per_side_bp": bp(README_BLEND_ONE_WAY + README_SLIP),
         "round_trip_bp": bp(2 * (README_BLEND_ONE_WAY + README_SLIP)),
         "notes": "code total_friction uses (avg_fee+slippage)*leverage once per side change"},
        {"scenario": "vip0_80_20_blend", "per_side_bp": bp(VIP0_BLEND_ONE_WAY), "round_trip_bp": bp(RT_VIP0_BLEND),
         "notes": "same 80/20 mix with the verified 5 bp taker"},
        {"scenario": "maker_entry_taker_stop_vip0", "per_side_bp": float("nan"), "round_trip_bp": bp(RT_MAKER_IN_TAKER_OUT),
         "notes": "2 bp maker entry + 5 bp taker stop. A stop-market cannot be a maker fill"},
    ]

    # data quality
    expected = int((open_ms[-1] - open_ms[0]) / BAR_MS) + 1
    gap_times = [str(ot[i]) for i in gap_at]
    quality = {
        "n_trade_bars": n,
        "first_utc": str(ot[0]),
        "last_utc": str(ot[-1]),
        "expected_bars_if_complete": expected,
        "missing_bars": int(expected - n),
        "n_gaps": int(gap_at.size),
        "gap_bar_open_utc": gap_times,
        "n_zero_volume": int(np.sum(vol == 0)),
        "n_high_lt_low": int(np.sum(h < lo)),
        "n_close_outside_hl": int(np.sum((c > h) | (c < lo))),
        "n_mark_rows_matched": int(np.isfinite(mark_c).sum()),
        "frac_trade_bars_with_mark": float(np.mean(np.isfinite(mark_c))),
        "n_funding_events": int(fund_ms.size),
        "n_funding_bad_hours_after_floor": bad_hours,
        "n_funding_dups_after_floor": n_fund_dup,
        "funding_rate_median": float(np.median(fund_rate)),
        "funding_rate_mean": float(np.mean(fund_rate)),
        "lag1_autocorr_5m": ac,
        "median_abs_5m_bp": float(np.median(np.abs(r_contig)) * 1e4),
        "mean_abs_5m_bp": float(np.mean(np.abs(r_contig)) * 1e4),
        "clock_1h_median_abs_bp": hour_stats["p50"],
        "clock_1h_n": hour_stats["n"],
        "median_close_to_next_open_gap_bp": float(np.median(gap_bp)),
        "p99_close_to_next_open_gap_bp": float(np.percentile(gap_bp, 99)),
        "median_tick_bp": float(np.median(tick_bp)),
        "median_step_notional_usdt": float(np.median(step_notional)),
        "frac_step_notional_below_50usdt": float(np.mean(step_notional < 50.0)),
        "hist_equals_macd_diff_disagreements_on_valid": hist_disagree,
        "n_long_and_short_both_true": n_both,
        "n_direct_flips": int(flips.sum()),
        "warmup_bars": WARMUP,
        "n_eval_bars": n_eval,
        "frac_eval_bars_in_session": float(session[eval_bars].mean()),
        "sma_vs_wilder_atr_median_ratio": float(np.nanmedian(
            atr_sma[valid_atr] / atr[valid_atr]
        )),
    }

    # session forward-return contrast on purged entries, written into session_rows
    fwd_df_tmp = pd.DataFrame(fwd_rows)
    for hz in HORIZONS:
        a = fwd_df_tmp[(fwd_df_tmp["slice"] == "session_12_20") & (fwd_df_tmp["side"] == "all")
                       & (fwd_df_tmp["horizon_bars"] == hz)]
        b = fwd_df_tmp[(fwd_df_tmp["slice"] == "session_rest") & (fwd_df_tmp["side"] == "all")
                       & (fwd_df_tmp["horizon_bars"] == hz)]
        if a.empty or b.empty:
            continue
        # Welch on the underlying purged returns would need the arrays; the table
        # already has means. Reconstruct Welch from stored n is impossible without
        # variances. Compute it directly here.
        ret, _, _, ok = cached[hz]
        ses = session[idx_all] & ok
        rest = (~session[idx_all]) & ok
        # purge within each group
        def purged_vals(mask):
            pos = np.flatnonzero(mask)
            keep = purge_mask(idx_all[pos], hz)
            return ret[pos[keep]]
        va, vb = purged_vals(ses), purged_vals(rest)
        t, df_, ma, mb, na, nb = welch(va, vb)
        session_rows.append({
            "metric": f"purged_fwd_gross_{HORIZON_LABEL[hz]}",
            "group": "session_minus_rest",
            "n": int(na + nb),
            "median_bp": float("nan"),
            "mean_bp": bp(ma - mb) if np.isfinite(ma) and np.isfinite(mb) else float("nan"),
            "welch_t_session_minus_rest": t,
            "welch_df": df_,
            "note": f"purged means session {bp(ma):.4f} bp (n={na}) rest {bp(mb):.4f} bp (n={nb})",
        })

    print("writing outputs", flush=True)
    pd.DataFrame(cost_rows).to_csv(OUT / "an_cost_table.csv", index=False)
    pd.DataFrame(move_rows).to_csv(OUT / "an_move_distribution.csv", index=False)
    pd.DataFrame(atr_rows).to_csv(OUT / "an_atr_distribution.csv", index=False)
    pd.DataFrame(sig_rows).to_csv(OUT / "an_signal_counts.csv", index=False)
    pd.DataFrame(year_rows).to_csv(OUT / "an_signal_by_year.csv", index=False)
    pd.DataFrame(session_rows).to_csv(OUT / "an_session_tests.csv", index=False)
    pd.DataFrame(fwd_rows).to_csv(OUT / "an_forward_returns.csv", index=False)
    pd.DataFrame(flip_rows).to_csv(OUT / "an_flip_sensitivity.csv", index=False)
    pd.DataFrame(geo_rows).to_csv(OUT / "an_stop_tp_geometry.csv", index=False)
    pd.DataFrame(liq_rows).to_csv(OUT / "an_liq_check.csv", index=False)

    summary = {
        "runtime_sec": time.time() - t0,
        "quality": quality,
        "long_liq": LONG_LIQ,
        "short_liq": SHORT_LIQ,
        "costs_rt_bp": {r["scenario"]: r["round_trip_bp"] for r in cost_rows},
        "atr_rows": atr_rows,
        "signal_rows": sig_rows,
        "year_full": [r for r in year_rows if r["year"] == "full"][0],
        "liq": liq_rows[0],
        "move_medians_bp": {f"{r['sample']}_{r['horizon']}": r["p50"] for r in move_rows},
    }
    with open(OUT / "an_summary.json", "w") as f:
        json.dump(json_ready(summary), f, indent=2)

    # concise stdout for the log
    print("--- KEY ---", flush=True)
    print("median_abs_5m_bp", quality["median_abs_5m_bp"], "ac", quality["lag1_autocorr_5m"],
          "clock_1h", quality["clock_1h_median_abs_bp"], flush=True)
    print("LONG_LIQ", LONG_LIQ, "SHORT_LIQ", SHORT_LIQ, flush=True)
    print("fresh", int(idx_all.size), "per_day", per_day, "median_daily", med_day, flush=True)
    full_fwd = [r for r in fwd_rows if r["slice"] == "full" and r["side"] == "all"]
    for r in full_fwd:
        print("FWD", r["horizon"], "n", r["n"], "gross_bp", round(r["mean_gross_bp"], 4),
              "nw_t", round(r["nw_t_gross"], 3), "purged_t", round(r["purged_t_gross"], 3),
              "net10", round(r["mean_net_rt10_bp"], 4), "purged_t_net10", round(r["purged_t_net_rt10"], 3),
              flush=True)
    for r in geo_rows:
        if r["slice"] == "full" and r["side"] == "all":
            print("GEO", r["trade"], "n", r["n"], "target", round(r["target_first_rate"], 4),
                  "winR", round(r["win_rate_gross_R_gt_0"], 4),
                  "meanR", round(r["mean_gross_R"], 4),
                  "net10", round(r["mean_net_R_rt10"], 4),
                  "purged_t_net", round(r["purged_t_net_rt10"], 3) if np.isfinite(r["purged_t_net_rt10"]) else None,
                  flush=True)
    print("LIQ hits", liq_rows[0]["n_hit_side_specific"], "of", liq_rows[0]["n_mark_complete"],
          "max", liq_rows[0]["mark_adv_max"], flush=True)
    print(f"done in {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
