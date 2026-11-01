#!/usr/bin/env python3
"""Locked Hyperliquid BTC 5m Donchian breakout smoke test.

Parameters are copied from the author note and the backtest lock.
This script does not search parameters, does not place orders, and
does not approve live trading.

Fill model (author variant only):
- Research fill at the signal 5m close. One position. No pyramid. No flip.
- No exit on the entry bar. A signal on an exit bar is ignored.
- Donchian and volume use the prior 20 completed 5m bars, signal bar excluded.
- 1h EMA200 (span 200, adjust=False, alpha=2/201) must already be defined.
  The 1h bar used is the latest whose close time is <= the 5m close time.
- Long stop P*(1-0.007), target P*(1+0.008) for 50%, then trail 0.3%.
  Short is the mirror. Before the scale-out, only the hard stop exists.
- Fee 0.045% of notional on the entry and on each exit fill.
  Account starts at 5000. Each trade risks 1% of current equity at the 0.7%
  stop, before fees. Margin = notional / 20. The book flattens and stays
  flat after a 20% peak-to-trough equity drawdown. Loss on one trade is
  capped at the margin posted.
- FUNDING, CPI/FOMC calendar, liquidation, and extra slippage are not applied.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import statsmodels.api as sm

    HAS_STATSMODELS = True
except Exception:  # noqa: BLE001 — absence is a reported result, not a fallback Sharpe
    sm = None
    HAS_STATSMODELS = False


URL = "https://api.hyperliquid.xyz/info"
BINANCE_KLINES = "https://fapi.binance.com/fapi/v1/klines"
BINANCE_SYMBOL = "BTCUSDT"
START_MS = 1730419200000  # 2024-11-01, same anchor the feasibility probe used
# Hyperliquid candleSnapshot returns no 5m bars before 2026-10-15. Six months
# of 5m candles are loaded from Binance USD-M instead. The 1h series starts
# earlier so the 200-hour EMA is already defined on the first 5m bar.
SIX_MONTH_5M_START = datetime(2026, 5, 1, tzinfo=timezone.utc)
SIX_MONTH_1H_START = datetime(2026, 4, 1, tzinfo=timezone.utc)

DONCHIAN_N = 20
VOL_N = 20
VOL_MULT = 1.5
EMA_SPAN = 200
EMA_ALPHA = 2.0 / 201.0
STOP_PCT = 0.007
TARGET_PCT = 0.008
TRAIL_PCT = 0.003
SCALE_FRAC = 0.5
LEVERAGE = 20.0
FEE = 0.00045
INITIAL_EQUITY = 5000.0
TRADE_MARGIN = 1000.0
RISK_FRACTION = 0.01
MAX_DRAWDOWN_HALT = 0.20
DIAG_COST = 0.00090  # 0.045% in and 0.045% out, price space, not leveraged
FORWARD_BARS = 20
BARS_PER_YEAR = 365.25 * 24.0 * 12.0
PRIOR_TRIALS = 4  # two written timeframes x two written exits

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "donchian_5m_6m"
SCRIPT_PATH = Path(__file__).resolve()


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mean_std_t(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "mean": "not computed",
            "stdev": "not computed",
            "t_stat": "not computed",
            "reason": "no observations",
        }
    mean = float(sum(values) / n)
    if n < 2:
        return {
            "n": n,
            "mean": mean,
            "stdev": "not computed",
            "t_stat": "not computed",
            "reason": "n < 2",
        }
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    if var <= 0.0:
        return {
            "n": n,
            "mean": mean,
            "stdev": 0.0,
            "t_stat": "not computed",
            "reason": "zero sample variance",
        }
    stdev = math.sqrt(var)
    t_stat = mean / (stdev / math.sqrt(n))
    return {"n": n, "mean": mean, "stdev": stdev, "t_stat": t_stat, "reason": None}


def max_drawdown(equities: list[float]) -> float:
    """Peak-to-trough on an ordered equity path. Negative or zero."""
    if not equities:
        return 0.0
    peak = equities[0]
    worst = 0.0
    for eq in equities:
        if peak <= 0.0:
            break
        if eq > peak:
            peak = eq
        dd = eq / peak - 1.0
        if dd < worst:
            worst = dd
    return float(worst)


def book_fill(pos: dict, frac: float, price: float, reason: str) -> None:
    if frac <= 0.0:
        raise RuntimeError("fill fraction must be positive")
    if frac - pos["remaining"] > 1e-12:
        raise RuntimeError("fill exceeds remaining fraction")
    pnl = frac * pos["notional"] * pos["dir"] * (price - pos["entry"]) / pos["entry"]
    fee = FEE * frac * pos["notional"]
    pos["realized_pnl"] += pnl
    pos["fees"] += fee
    pos["remaining"] -= frac
    pos["fills"].append({"reason": reason, "frac": frac, "price": price, "pnl": pnl, "fee": fee})


def _stake_value(pos: dict, unreal: float = 0.0) -> float:
    """Isolated stake after price pnl and fees. The rest of the account is idle."""
    return max(0.0, pos["stake"] + pos["realized_pnl"] - pos["fees"] + unreal)


def mtm(pos: dict, price: float) -> float:
    unreal = pos["remaining"] * pos["notional"] * pos["dir"] * (price - pos["entry"]) / pos["entry"]
    return pos["idle"] + _stake_value(pos, unreal)


def flat_equity(pos: dict) -> float:
    if pos["remaining"] > 1e-9:
        raise RuntimeError("flat equity requested while position remains")
    return pos["idle"] + _stake_value(pos, 0.0)


def run_backtest(
    bars: list[dict],
    signals: list[int],
    initial_equity: float = INITIAL_EQUITY,
    trade_margin: float | None = None,
    risk_fraction: float | None = RISK_FRACTION,
    max_drawdown: float | None = MAX_DRAWDOWN_HALT,
) -> dict:
    """Simulate the locked position rules.

    Drawdown path:
    - Entry bar: post-fee equity at the signal close only.
    - Exit bar: open print, then each fill at the price the rule actually books.
      A print beyond the fill is not marked.
    - Hold bar: open, then favorable print, then adverse print, then close.
      Favorable-before-adverse is a pessimistic order of two real prints.
    """
    if len(bars) != len(signals):
        raise RuntimeError("signal length does not match bars")

    equity = float(initial_equity)
    peak = equity
    halted = False
    position = None
    trades = []
    marks = [{"bar_index": -1, "close_time_ms": None, "mark": "start", "equity": equity, "dir": 0}]
    close_path = [equity]
    skipped_in_position = 0
    skipped_insufficient_cash = 0
    skipped_drawdown_halt = 0
    entries = 0
    ruined = False
    fixed_stake = trade_margin is not None

    def push(bar_index: int, close_time_ms, label: str, eq: float, direction: int) -> None:
        marks.append(
            {
                "bar_index": bar_index,
                "close_time_ms": close_time_ms,
                "mark": label,
                "equity": float(eq),
                "dir": direction,
            }
        )

    def finish(pos: dict, bar_index: int, close_time_ms: int) -> float:
        eq = flat_equity(pos)
        push(bar_index, close_time_ms, "flat", eq, 0)
        trades.append(_trade_row(pos, close_time_ms, bar_index, eq))
        return eq

    for i, bar in enumerate(bars):
        o = float(bar["o"])
        h = float(bar["h"])
        l = float(bar["l"])
        c = float(bar["c"])
        t_ms = int(bar["close_time_ms"])
        sig = int(signals[i])
        end_equity = equity
        end_dir = 0

        if position is not None and position["entry_i"] < i:
            d = position["dir"]
            push(i, t_ms, "open", mtm(position, o), d)

            def mark_hold_extremes() -> None:
                # Position is still on after this bar, so both prints are real marks.
                # Favorable first, then adverse: the sequence inside the bar is unknown,
                # and this order does not hide an intrabar give-back.
                if d == 1:
                    push(i, t_ms, "favorable", mtm(position, h), d)
                    push(i, t_ms, "adverse", mtm(position, l), d)
                else:
                    push(i, t_ms, "favorable", mtm(position, l), d)
                    push(i, t_ms, "adverse", mtm(position, h), d)

            if not position["scaled"]:
                if d == 1:
                    stop_hit = o <= position["stop"] or l <= position["stop"]
                    target_hit = h >= position["target"] or o >= position["target"]
                else:
                    stop_hit = o >= position["stop"] or h >= position["stop"]
                    target_hit = l <= position["target"] or o <= position["target"]

                if stop_hit:
                    if d == 1:
                        fill = o if o <= position["stop"] else position["stop"]
                        reason = "stop_at_open" if o <= position["stop"] else "stop_at_level"
                    else:
                        fill = o if o >= position["stop"] else position["stop"]
                        reason = "stop_at_open" if o >= position["stop"] else "stop_at_level"
                    book_fill(position, position["remaining"], fill, reason)
                    equity = finish(position, i, t_ms)
                    position = None
                    end_equity = equity
                    if sig != 0:
                        skipped_in_position += 1
                elif target_hit:
                    # Fills are at the target and, if touched, the trail. The high is not
                    # marked as a full-size gain: the scaled half is sold at the target.
                    if d == 1:
                        extreme_px = h
                        trail = h * (1.0 - TRAIL_PCT)
                        rem_hit = l <= trail
                        adverse_px = l
                    else:
                        extreme_px = l
                        trail = l * (1.0 + TRAIL_PCT)
                        rem_hit = h >= trail
                        adverse_px = h
                    if not rem_hit:
                        # Stop was not hit and the new trail is not hit, so this print
                        # was lived at full size. Mark it before the scale-out.
                        push(i, t_ms, "adverse", mtm(position, adverse_px), d)
                    book_fill(position, SCALE_FRAC, position["target"], "scale_at_target")
                    push(i, t_ms, "scale", mtm(position, position["target"]), d)
                    position["extreme"] = extreme_px
                    if rem_hit:
                        book_fill(position, position["remaining"], trail, "trail_same_bar")
                        equity = finish(position, i, t_ms)
                        position = None
                        end_equity = equity
                        if sig != 0:
                            skipped_in_position += 1
                    else:
                        position["scaled"] = True
                        end_equity = mtm(position, c)
                        end_dir = d
                        push(i, t_ms, "close", end_equity, d)
                        if sig != 0:
                            skipped_in_position += 1
                else:
                    mark_hold_extremes()
                    end_equity = mtm(position, c)
                    end_dir = d
                    push(i, t_ms, "close", end_equity, d)
                    if sig != 0:
                        skipped_in_position += 1
            else:
                extreme = position["extreme"]
                if d == 1:
                    trail = extreme * (1.0 - TRAIL_PCT)
                    if o <= trail:
                        fill, reason, hit = o, "trail_at_open", True
                    elif l <= trail:
                        fill, reason, hit = trail, "trail_at_level", True
                    else:
                        fill, reason, hit = None, None, False
                else:
                    trail = extreme * (1.0 + TRAIL_PCT)
                    if o >= trail:
                        fill, reason, hit = o, "trail_at_open", True
                    elif h >= trail:
                        fill, reason, hit = trail, "trail_at_level", True
                    else:
                        fill, reason, hit = None, None, False
                if hit:
                    book_fill(position, position["remaining"], fill, reason)
                    equity = finish(position, i, t_ms)
                    position = None
                    end_equity = equity
                    if sig != 0:
                        skipped_in_position += 1
                else:
                    mark_hold_extremes()
                    if d == 1:
                        position["extreme"] = max(extreme, h)
                    else:
                        position["extreme"] = min(extreme, l)
                    end_equity = mtm(position, c)
                    end_dir = d
                    push(i, t_ms, "close", end_equity, d)
                    if sig != 0:
                        skipped_in_position += 1
        elif position is None and sig != 0 and not halted:
            if fixed_stake:
                stake = float(trade_margin)
                notional = LEVERAGE * stake
                can_fund = equity + 1e-9 >= stake
            else:
                notional = float(risk_fraction) * equity / STOP_PCT
                stake = notional / LEVERAGE
                can_fund = stake > 0.0 and stake <= equity + 1e-9
            if not can_fund:
                skipped_insufficient_cash += 1
                ruined = equity <= 0.0
                end_equity = equity
                end_dir = 0
            else:
                position = {
                    "dir": sig,
                    "entry": c,
                    "entry_i": i,
                    "entry_time_ms": t_ms,
                    "notional": notional,
                    "stake": stake,
                    "idle": equity - stake,
                    "equity_at_entry": equity,
                    "remaining": 1.0,
                    "realized_pnl": 0.0,
                    "fees": FEE * notional,
                    "scaled": False,
                    "extreme": None,
                    "stop": c * (1.0 - STOP_PCT) if sig == 1 else c * (1.0 + STOP_PCT),
                    "target": c * (1.0 + TARGET_PCT) if sig == 1 else c * (1.0 - TARGET_PCT),
                    "fills": [],
                }
                entries += 1
                end_equity = mtm(position, c)
                end_dir = sig
                push(i, t_ms, "entry", end_equity, sig)
        elif position is not None and position["entry_i"] == i:
            # Defensive: the entry bar is handled above when the position is opened.
            end_equity = mtm(position, c)
            end_dir = position["dir"]
        else:
            if sig != 0 and halted:
                skipped_drawdown_halt += 1
            elif sig != 0 and fixed_stake and equity + 1e-9 < float(trade_margin):
                skipped_insufficient_cash += 1
                ruined = equity <= 0.0
            end_equity = equity
            end_dir = 0

        if end_equity > peak:
            peak = end_equity
        elif (
            max_drawdown is not None
            and not halted
            and peak > 0.0
            and (end_equity / peak - 1.0) <= -float(max_drawdown)
        ):
            if position is not None and position["remaining"] > 1e-9:
                book_fill(position, position["remaining"], c, "drawdown_flatten")
                equity = finish(position, i, t_ms)
                position = None
                end_equity = equity
                end_dir = 0
            halted = True

        close_path.append(end_equity)
        if end_equity <= 0.0 and position is None:
            ruined = True

    open_trade = None
    if position is not None:
        last = bars[-1]
        open_trade = {
            "dir": position["dir"],
            "entry": position["entry"],
            "entry_time_ms": position["entry_time_ms"],
            "remaining": position["remaining"],
            "scaled": position["scaled"],
            "mtm_equity": mtm(position, float(last["c"])),
            "notional": position["notional"],
        }

    return {
        "trades": trades,
        "marks": marks,
        "close_path": close_path,
        "final_equity_realized": equity,
        "open_trade": open_trade,
        "entries": entries,
        "signals_skipped_because_in_position": skipped_in_position,
        "signals_skipped_insufficient_cash": skipped_insufficient_cash,
        "signals_skipped_drawdown_halt": skipped_drawdown_halt,
        "halted": halted,
        "peak_equity": peak,
        "trade_margin": trade_margin,
        "risk_fraction": None if fixed_stake else risk_fraction,
        "max_drawdown_halt": max_drawdown,
        "ruined": ruined,
    }


def _trade_row(pos: dict, exit_time_ms: int, exit_i: int, equity_after: float) -> dict:
    net = equity_after - pos["equity_at_entry"]
    scale = next((f for f in pos["fills"] if f["reason"] == "scale_at_target"), None)
    remainder = pos["fills"][-1]
    return {
        "dir": "long" if pos["dir"] == 1 else "short",
        "entry_time_ms": pos["entry_time_ms"],
        "exit_time_ms": exit_time_ms,
        "entry_bar": pos["entry_i"],
        "exit_bar": exit_i,
        "bars_held": exit_i - pos["entry_i"],
        "entry_price": pos["entry"],
        "stop_price": pos["stop"],
        "target_price": pos["target"],
        "notional": pos["notional"],
        "equity_at_entry": pos["equity_at_entry"],
        "scale_price": None if scale is None else scale["price"],
        "remainder_exit_price": remainder["price"],
        "remainder_reason": remainder["reason"],
        "gross_pnl": pos["realized_pnl"],
        "fees": pos["fees"],
        "net_pnl": net,
        "net_return_on_equity": net / pos["equity_at_entry"],
        "equity_after": equity_after,
        "fill_count": len(pos["fills"]),
    }


def aligned_hour_index(hour_close_ms: np.ndarray, five_close_ms: int) -> int:
    """Latest 1h bar whose close time is <= the 5m close time. -1 if none."""
    idx = int(np.searchsorted(hour_close_ms, five_close_ms, side="right") - 1)
    if idx < 0:
        return -1
    return idx


def compute_ema(closes: np.ndarray) -> np.ndarray:
    """pandas ewm(span=200, adjust=False). Seeded on the first close."""
    series = pd.Series(closes, dtype="float64")
    ema = series.ewm(span=EMA_SPAN, adjust=False).mean().to_numpy(dtype=float)
    return ema


def build_signals(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    hour_index: np.ndarray,
    hour_close: np.ndarray,
    hour_ema: np.ndarray,
    use_volume: bool,
    use_ema: bool,
) -> np.ndarray:
    n = len(close)
    sig = np.zeros(n, dtype=int)
    for i in range(n):
        if i < DONCHIAN_N:
            continue
        d_high = float(np.max(high[i - DONCHIAN_N : i]))
        d_low = float(np.min(low[i - DONCHIAN_N : i]))
        if use_volume:
            if i < VOL_N:
                continue
            vol_ma = float(np.mean(volume[i - VOL_N : i]))
            vol_ok = float(volume[i]) > VOL_MULT * vol_ma
        else:
            vol_ok = True
        if use_ema:
            hidx = int(hour_index[i])
            if hidx < EMA_SPAN - 1:
                continue
            h_close = float(hour_close[hidx])
            h_ema = float(hour_ema[hidx])
            long_trend = h_close > h_ema
            short_trend = h_close < h_ema
        else:
            long_trend = True
            short_trend = True
        c = float(close[i])
        long_sig = c > d_high and vol_ok and long_trend
        short_sig = c < d_low and vol_ok and short_trend
        if long_sig and not short_sig:
            sig[i] = 1
        elif short_sig and not long_sig:
            sig[i] = -1
    return sig


def event_returns(close: np.ndarray, signals: np.ndarray) -> list[dict]:
    events = []
    last = len(close) - 1
    for i, sig in enumerate(signals.tolist()):
        if sig == 0 or i + FORWARD_BARS > last:
            continue
        raw = float(close[i + FORWARD_BARS] / close[i] - 1.0)
        net = sig * raw - DIAG_COST
        events.append({"i": i, "sig": int(sig), "net": net})
    return events


def non_overlapping(events: list[dict]) -> list[dict]:
    kept = []
    last_i = None
    for event in events:
        if last_i is None or event["i"] >= last_i + FORWARD_BARS:
            kept.append(event)
            last_i = event["i"]
    return kept


def hac_tstat(values: list[float]) -> dict:
    if not HAS_STATSMODELS:
        return {"hac_t_stat": "not computed", "reason": "statsmodels is not installed"}
    n = len(values)
    maxlags = FORWARD_BARS - 1
    if n <= maxlags + 2:
        return {
            "hac_t_stat": "not computed",
            "reason": f"overlapping event count {n} is too small for Newey-West maxlags={maxlags}",
        }
    y = np.asarray(values, dtype=float)
    x = np.ones((n, 1))
    fitted = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return {
        "hac_t_stat": float(fitted.tvalues[0]),
        "maxlags": maxlags,
        "reason": (
            "Newey-West on the ordered overlapping event returns. "
            "Events are not equally spaced, so this is not calendar-time HAC."
        ),
    }


def sign_flip(full_mean, other_mean) -> str:
    if not isinstance(full_mean, float) or not isinstance(other_mean, float):
        return "not computed"
    if full_mean == 0.0 or other_mean == 0.0:
        return "no"
    return "yes" if (full_mean > 0.0) != (other_mean > 0.0) else "no"


def fetch_candles(interval: str, start_ms: int, fetched_at_ms: int) -> tuple[dict, bytes]:
    payload = {"type": "candleSnapshot", "req": {"coin": "BTC", "interval": interval, "startTime": start_ms}}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        URL,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "donchian-5m-backtest"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        raise RuntimeError(f"{interval} candleSnapshot HTTP {exc.code}: {body[:300]!r}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{interval} candleSnapshot network error: {exc}") from exc
    meta = {
        "url": URL,
        "http_status": status,
        "request": payload,
        "fetched_at_ms": fetched_at_ms,
        "fetched_at_utc": utc_iso(fetched_at_ms),
        "nbytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return meta, raw


def fetch_binance_klines(interval: str, start_ms: int, end_ms: int, fetched_at_ms: int) -> tuple[dict, bytes]:
    """Page Binance USD-M klines. Each response holds at most 1,500 bars."""
    interval_ms = 300_000 if interval == "5m" else 3_600_000
    cursor = start_ms
    pages = []
    combined: list[dict] = []
    while cursor < end_ms:
        query = (
            f"{BINANCE_KLINES}?symbol={BINANCE_SYMBOL}&interval={interval}"
            f"&startTime={cursor}&endTime={end_ms - 1}&limit=1500"
        )
        req = urllib.request.Request(query, headers={"User-Agent": "donchian-5m-backtest"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                status = int(resp.status)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            raise RuntimeError(f"Binance {interval} HTTP {exc.code}: {body[:300]!r}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Binance {interval} network error: {exc}") from exc
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Binance {interval} response is not JSON") from exc
        if isinstance(rows, dict):
            raise RuntimeError(f"Binance {interval} error payload: {rows}")
        if not rows:
            break
        pages.append({"url": query, "http_status": status, "count": len(rows), "nbytes": len(raw)})
        print(f"BINANCE {interval} page {len(pages)} bars {len(rows)}", file=sys.stderr, flush=True)
        last_open = int(rows[-1][0])
        for row in rows:
            open_ms = int(row[0])
            if open_ms < cursor or open_ms >= end_ms:
                continue
            combined.append(
                {
                    "t": open_ms,
                    "T": int(row[6]),
                    "s": "BTC",
                    "i": interval,
                    "o": row[1],
                    "h": row[2],
                    "l": row[3],
                    "c": row[4],
                    "v": row[5],
                    "n": int(row[8]),
                }
            )
        next_cursor = last_open + interval_ms
        if next_cursor <= cursor:
            raise RuntimeError(f"Binance {interval} page did not advance")
        cursor = next_cursor
        if len(rows) < 1500:
            break
    if not combined:
        raise RuntimeError(f"Binance {interval} returned 0 bars")
    body = json.dumps(combined).encode("utf-8")
    meta = {
        "url": BINANCE_KLINES,
        "symbol": BINANCE_SYMBOL,
        "interval": interval,
        "http_status": 200,
        "pages": len(pages),
        "page_log": pages,
        "request": {"startTime": start_ms, "endTime": end_ms},
        "fetched_at_ms": fetched_at_ms,
        "fetched_at_utc": utc_iso(fetched_at_ms),
        "nbytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "why_not_hyperliquid": (
            "Hyperliquid candleSnapshot returned 0 BTC 5m bars for every tested window "
            "before 2026-10-15. A bounded request from 2026-10-01 to 2026-10-20 starts at "
            "2026-10-15T02:35:00Z. That history is about 17 days, so the six-month window "
            "uses Binance USD-M BTCUSDT klines."
        ),
    }
    return meta, body


def load_candles(raw: bytes, interval: str, interval_ms: int, fetched_at_ms: int) -> tuple[pd.DataFrame, dict]:
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{interval} response is not JSON") from exc
    if not isinstance(rows, list):
        raise RuntimeError(f"{interval} response is not a list")
    if len(rows) == 0:
        raise RuntimeError(f"{interval} candleSnapshot returned 0 bars")

    parsed = []
    for row in rows:
        try:
            t_open = int(row["t"])
            t_end = int(row["T"])
            parsed.append(
                {
                    "t": t_open,
                    "T": t_end,
                    "o": float(row["o"]),
                    "h": float(row["h"]),
                    "l": float(row["l"]),
                    "c": float(row["c"]),
                    "v": float(row["v"]),
                    "n": int(row["n"]) if "n" in row else None,
                    "s": row.get("s"),
                    "i": row.get("i"),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"{interval} candle row could not be parsed: {exc}") from exc

    frame = pd.DataFrame(parsed).sort_values("t").drop_duplicates("t", keep="last").reset_index(drop=True)
    expected_span = interval_ms - 1
    span = frame["T"] - frame["t"]
    span_mismatch = int((span != expected_span).sum())
    # t is the open. Close time is open + interval, per the lock.
    frame["close_time_ms"] = frame["t"] + interval_ms
    forming = frame["close_time_ms"] > fetched_at_ms
    forming_dropped = int(forming.sum())
    frame = frame.loc[~forming].reset_index(drop=True)
    if frame.empty:
        raise RuntimeError(f"{interval} has no closed bars at the fetch timestamp")

    bad_ohlc = int(
        (
            (frame["h"] < frame["l"])
            | (frame["h"] < frame["o"])
            | (frame["h"] < frame["c"])
            | (frame["l"] > frame["o"])
            | (frame["l"] > frame["c"])
            | (frame["c"] <= 0.0)
            | (frame["o"] <= 0.0)
        ).sum()
    )
    steps = frame["t"].diff().dropna()
    gap_count = int((steps != interval_ms).sum())
    zero_volume = int((frame["v"] <= 0.0).sum())
    info = {
        "raw_count": len(rows),
        "closed_count": int(len(frame)),
        "forming_bars_dropped": forming_dropped,
        "open_to_T_mismatch_count": span_mismatch,
        "expected_T_minus_t": expected_span,
        "gap_count": gap_count,
        "zero_volume_count": zero_volume,
        "bad_ohlc_count": bad_ohlc,
        "first_open_ms": int(frame["t"].iloc[0]),
        "last_open_ms": int(frame["t"].iloc[-1]),
        "first_close_ms": int(frame["close_time_ms"].iloc[0]),
        "last_close_ms": int(frame["close_time_ms"].iloc[-1]),
        "first_open_utc": utc_iso(int(frame["t"].iloc[0])),
        "last_close_utc": utc_iso(int(frame["close_time_ms"].iloc[-1])),
        "coin_values": sorted({str(x) for x in frame["s"].dropna().unique()}),
        "interval_values": sorted({str(x) for x in frame["i"].dropna().unique()}),
        "duplicate_open_times_dropped": int(len(rows) - (int(len(frame)) + forming_dropped)),
    }
    if bad_ohlc:
        raise RuntimeError(f"{interval} has {bad_ohlc} OHLC-inconsistent bars; backtest not run")
    if len(frame) > 2 and gap_count > (len(frame) - 1) / 2:
        raise RuntimeError(f"{interval} is mostly gaps ({gap_count}); backtest not run")
    return frame, info


def outlier_count(close: np.ndarray) -> dict:
    if len(close) < 3:
        return {"abs_log_return_gt_10_sigma": "not computed", "reason": "too few bars"}
    rets = np.diff(np.log(close))
    std = float(rets.std(ddof=1))
    if std == 0.0:
        return {"abs_log_return_gt_10_sigma": 0, "sigma": 0.0}
    z = rets / std
    return {"abs_log_return_gt_10_sigma": int(np.sum(np.abs(z) > 10.0)), "sigma_log_return": std}


def sharpe_from_close_path(close_path: list[float]) -> dict:
    bars_per_year = BARS_PER_YEAR
    if len(close_path) < 3:
        return {
            "net_sharpe_computed": False,
            "net_sharpe_annualized": "not computed",
            "reason": "fewer than 2 bar returns",
            "bars_per_year": bars_per_year,
            "annualization": "mean(bar return) / sample_stdev(bar return) * sqrt(bars_per_year), rf = 0",
        }
    rets = []
    for prev, cur in zip(close_path[:-1], close_path[1:]):
        if prev <= 0.0:
            return {
                "net_sharpe_computed": False,
                "net_sharpe_annualized": "not computed",
                "reason": "equity hit non-positive, bar-return Sharpe stopped",
                "bars_per_year": bars_per_year,
                "annualization": "mean(bar return) / sample_stdev(bar return) * sqrt(bars_per_year), rf = 0",
            }
        rets.append(cur / prev - 1.0)
    stats = mean_std_t(rets)
    if not isinstance(stats["t_stat"], float):
        return {
            "net_sharpe_computed": False,
            "net_sharpe_annualized": "not computed",
            "reason": stats["reason"],
            "bar_return_mean": stats["mean"],
            "bar_return_n": stats["n"],
            "bars_per_year": bars_per_year,
            "annualization": "mean(bar return) / sample_stdev(bar return) * sqrt(bars_per_year), rf = 0",
            "risk_free_rate": 0.0,
        }
    sharpe = stats["mean"] / stats["stdev"] * math.sqrt(bars_per_year)
    return {
        "net_sharpe_computed": True,
        "net_sharpe_annualized": sharpe,
        "reason": None,
        "bar_return_mean": stats["mean"],
        "bar_return_stdev": stats["stdev"],
        "bar_return_n": stats["n"],
        "bars_per_year": bars_per_year,
        "annualization": "mean(5m close-to-close equity return) / sample stdev * sqrt(365.25*24*12), rf = 0",
        "risk_free_rate": 0.0,
        "path": "end-of-bar equity, after fills. Flat bars are included. This is not a per-trade Sharpe.",
    }


def diagnostic_block(close: np.ndarray, signals: np.ndarray, label: str) -> dict:
    events = event_returns(close, signals)
    nets = [e["net"] for e in events]
    stats = mean_std_t(nets)
    kept = non_overlapping(events)
    kept_stats = mean_std_t([e["net"] for e in kept])
    hac = hac_tstat(nets)
    block = {
        "label": label,
        "event_count_with_forward_window": stats["n"],
        "signals_without_forward_window": int(np.sum(signals != 0) - stats["n"])
        if isinstance(stats["n"], int)
        else None,
        "overlapping": {
            "n": stats["n"],
            "mean_net_20bar": stats["mean"],
            "t_stat": stats["t_stat"],
            "t_stat_label": "optimistic" if isinstance(stats["t_stat"], float) else stats["reason"],
            "note": "20-bar windows overlap, so the ordinary t-stat overstates independence.",
        },
        "non_overlapping": {
            "n": kept_stats["n"],
            "mean_net_20bar": kept_stats["mean"],
            "t_stat": kept_stats["t_stat"],
            "rule": "keep an event only if its bar index is at least 20 bars after the previous kept event",
        },
        "hac": hac,
        "definition": "direction * (close[t+20]/close[t] - 1) - 0.00090",
    }
    if block["signals_without_forward_window"] is None:
        block["signals_without_forward_window"] = "not computed"
    return block


def write_trades(path: Path, trades: list[dict]) -> None:
    fields = [
        "dir",
        "entry_time_utc",
        "exit_time_utc",
        "entry_time_ms",
        "exit_time_ms",
        "entry_bar",
        "exit_bar",
        "bars_held",
        "entry_price",
        "stop_price",
        "target_price",
        "notional",
        "equity_at_entry",
        "scale_price",
        "remainder_exit_price",
        "remainder_reason",
        "gross_pnl",
        "fees",
        "net_pnl",
        "net_return_on_equity",
        "equity_after",
        "fill_count",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            row = dict(trade)
            row["entry_time_utc"] = utc_iso(int(trade["entry_time_ms"]))
            row["exit_time_utc"] = utc_iso(int(trade["exit_time_ms"]))
            writer.writerow(row)


def write_equity(path: Path, marks: list[dict]) -> None:
    fields = ["mark_seq", "bar_index", "close_time_ms", "close_time_utc", "mark", "equity", "dir"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for seq, mark in enumerate(marks):
            ct = mark["close_time_ms"]
            writer.writerow(
                {
                    "mark_seq": seq,
                    "bar_index": mark["bar_index"],
                    "close_time_ms": "" if ct is None else ct,
                    "close_time_utc": "" if ct is None else utc_iso(int(ct)),
                    "mark": mark["mark"],
                    "equity": repr(float(mark["equity"])),
                    "dir": mark["dir"],
                }
            )


def _approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(b))


def self_check() -> None:
    # EMA matches the locked recursion, and bar 199 is the first defined bar.
    alpha_series = pd.Series([1.0, 2.0, 4.0], dtype="float64").ewm(span=200, adjust=False).mean()
    alpha = 2.0 / 201.0
    if abs(float(alpha_series.iloc[0]) - 1.0) > 1e-15:
        raise AssertionError("EMA seed is not the first close")
    expected = (1.0 - alpha) * 1.0 + alpha * 2.0
    if abs(float(alpha_series.iloc[1]) - expected) > 1e-12:
        raise AssertionError("EMA alpha is not 2/201")
    if abs(EMA_ALPHA - alpha) > 1e-15:
        raise AssertionError("locked alpha constant drifted")

    hour_close = np.array([3_600_000, 7_200_000, 10_800_000], dtype=np.int64)
    if aligned_hour_index(hour_close, 3_600_000) != 0:
        raise AssertionError("exact hour close should use the just-closed hour")
    if aligned_hour_index(hour_close, 3_599_999) != -1:
        raise AssertionError("a 5m close before the first hour close has no hour")
    if aligned_hour_index(hour_close, 7_200_000) != 1:
        raise AssertionError("forming hour was selected")
    if aligned_hour_index(hour_close, 9_000_000) != 1:
        raise AssertionError("mid-hour alignment is not the previous close")

    # Donchian and volume exclude the signal bar.
    n = 21
    high = np.full(n, 10.0)
    low = np.full(n, 9.0)
    close = np.full(n, 9.5)
    volume = np.full(n, 100.0)
    close[20] = 10.5
    high[20] = 12.0  # must not enter the Donchian high
    volume[20] = 151.0  # passes only if the signal bar is excluded from the average
    hour_index = np.full(n, EMA_SPAN - 1)
    hour_c = np.array([10.0])
    hour_e = np.array([9.0])
    # pad hour arrays so index EMA_SPAN-1 exists
    hour_c = np.full(EMA_SPAN, 10.0)
    hour_e = np.full(EMA_SPAN, 9.0)
    hour_index = np.full(n, EMA_SPAN - 1)
    sig = build_signals(close, high, low, volume, hour_index, hour_c, hour_e, True, True)
    if int(sig[20]) != 1:
        raise AssertionError("signal bar leaked into Donchian or volume average")
    volume[20] = 150.0
    sig = build_signals(close, high, low, volume, hour_index, hour_c, hour_e, True, True)
    if int(sig[20]) != 0:
        raise AssertionError("volume test is not strict")
    volume[20] = 151.0
    hour_e[-1] = 10.0  # equal to hour close
    sig = build_signals(close, high, low, volume, hour_index, hour_c, hour_e, True, True)
    if int(sig[20]) != 0:
        raise AssertionError("equal EMA must block the entry")
    hour_e[-1] = 11.0
    low[20] = 8.0
    close[20] = 8.5
    sig = build_signals(close, high, low, volume, hour_index, hour_c, hour_e, True, True)
    if int(sig[20]) != -1:
        raise AssertionError("short signal failed")

    def bar(ms, o, h, l, c):
        return {"close_time_ms": ms, "o": o, "h": h, "l": l, "c": c}

    # Full stop, then a same-bar signal ignored, then a later stop that compounds.
    bars = [
        bar(0, 100, 100, 100, 100),
        bar(1, 100, 100, 99.0, 99.5),
        bar(2, 100, 100, 100, 100),
        bar(3, 100, 100, 99.0, 99.5),
    ]
    sigs = [1, 1, 1, 0]
    out = run_backtest(bars, sigs, 1.0, trade_margin=0.2)
    if len(out["trades"]) != 2:
        raise AssertionError(f"expected 2 compounded stops, got {len(out['trades'])}")
    if out["signals_skipped_because_in_position"] < 1:
        raise AssertionError("exit-bar signal was not ignored")
    first = out["trades"][0]
    if first["remainder_reason"] != "stop_at_level":
        raise AssertionError("stop fill price branch is wrong")
    if not _approx(first["remainder_exit_price"], 100.0 * (1.0 - STOP_PCT)):
        raise AssertionError("stop level is not 0.7%")
    # Fixed stake 0.2 at 20x. A full stop does not resize the next trade.
    check_notional = LEVERAGE * 0.2
    expected_net = check_notional * -STOP_PCT - FEE * check_notional * 2.0
    if not _approx(first["net_pnl"], expected_net):
        raise AssertionError(f"first stop net pnl {first['net_pnl']} != {expected_net}")
    second = out["trades"][1]
    if not _approx(second["notional"], check_notional):
        raise AssertionError("notional did not stay on the fixed stake")

    # No exit on the entry bar even if that bar's low is through the stop.
    bars = [bar(0, 100, 100, 90, 100), bar(1, 100, 100, 100, 100)]
    out = run_backtest(bars, [1, 0], 1.0, trade_margin=0.2)
    if out["trades"]:
        raise AssertionError("entry bar was allowed to stop out")
    if out["open_trade"] is None:
        raise AssertionError("entry did not stay open")

    # Gap through the stop fills at the open, not the stop, and not the low.
    bars = [bar(0, 100, 100, 100, 100), bar(1, 98.0, 98.5, 97.0, 98.2)]
    out = run_backtest(bars, [1, 0], 1.0, trade_margin=0.2)
    trade = out["trades"][0]
    if trade["remainder_reason"] != "stop_at_open" or not _approx(trade["remainder_exit_price"], 98.0):
        raise AssertionError("gap-through-stop fill is wrong")
    if trade["fill_count"] != 1:
        raise AssertionError("gap stop should be one full fill")

    # Target gap does not improve the scale fill. Remainder uses this bar's high.
    # open 102, high 103, low 101.5. target 100.8. trail = 103 * 0.997.
    bars = [bar(0, 100, 100, 100, 100), bar(1, 102.0, 103.0, 101.5, 102.5)]
    out = run_backtest(bars, [1, 0], 1.0, trade_margin=0.2)
    trade = out["trades"][0]
    if not _approx(trade["scale_price"], 100.0 * (1.0 + TARGET_PCT)):
        raise AssertionError("scale fill was improved above the target")
    trail = 103.0 * (1.0 - TRAIL_PCT)
    if not _approx(trade["remainder_exit_price"], trail):
        raise AssertionError("same-bar trail did not use this bar's high")
    if trade["remainder_reason"] != "trail_same_bar":
        raise AssertionError("same-bar remainder reason is wrong")

    # Later trail uses the extreme known BEFORE the bar.
    # Bar 1 scales and holds: high 100.8, low 100.7, trail = 100.8*0.997 = 100.4976.
    # Bar 2 high 102 must not tighten the stop before the low test.
    # low 100.60 is above 100.4976, so the remainder stays and extreme becomes 102.
    bars = [
        bar(0, 100, 100, 100, 100),
        bar(1, 100.0, 100.8, 100.7, 100.75),
        bar(2, 100.7, 102.0, 100.60, 101.8),
        bar(3, 101.8, 101.9, 101.8, 101.85),
    ]
    out = run_backtest(bars, [1, 0, 0, 0], 1.0, trade_margin=0.2)
    if out["trades"]:
        raise AssertionError("trail updated and stopped on the same later bar")
    if out["open_trade"] is None or abs(out["open_trade"]["remaining"] - 0.5) > 1e-12:
        raise AssertionError("remainder was not carried")

    # The next bar stops at the OLD trail if the low touches it, even if the high is higher.
    bars = [
        bar(0, 100, 100, 100, 100),
        bar(1, 100.0, 100.8, 100.7, 100.75),
        bar(2, 100.7, 102.0, 100.40, 101.0),
    ]
    out = run_backtest(bars, [1, 0, 0], 1.0, trade_margin=0.2)
    trade = out["trades"][0]
    old_trail = 100.8 * (1.0 - TRAIL_PCT)
    if not _approx(trade["remainder_exit_price"], old_trail):
        raise AssertionError("later trail filled at a same-bar updated extreme")

    # Stop is checked before the target on a bar that prints both.
    bars = [bar(0, 100, 100, 100, 100), bar(1, 100.0, 102.0, 99.0, 101.0)]
    out = run_backtest(bars, [1, 0], 1.0, trade_margin=0.2)
    trade = out["trades"][0]
    if trade["fill_count"] != 1 or trade["remainder_reason"] != "stop_at_level":
        raise AssertionError("stop did not dominate a same-bar target")
    if max(m["equity"] for m in out["marks"]) > 1.0 + 1e-12:
        raise AssertionError("stop bar booked the untouched high as equity")

    # Short mirror: gap through target does not improve, remainder trails off the low.
    bars = [bar(0, 100, 100, 100, 100), bar(1, 98.0, 98.4, 97.5, 98.1)]
    out = run_backtest(bars, [-1, 0], 1.0, trade_margin=0.2)
    trade = out["trades"][0]
    if not _approx(trade["scale_price"], 100.0 * (1.0 - TARGET_PCT)):
        raise AssertionError("short scale fill was improved")
    short_trail = 97.5 * (1.0 + TRAIL_PCT)
    if not _approx(trade["remainder_exit_price"], short_trail):
        raise AssertionError("short same-bar trail is wrong")

    # Short later bar must not tighten from this bar's low before the high test.
    bars = [
        bar(0, 100, 100, 100, 100),
        bar(1, 99.40, 99.45, 99.2, 99.30),
        bar(2, 99.30, 99.45, 98.0, 98.5),
    ]
    out = run_backtest(bars, [-1, 0, 0], 1.0, trade_margin=0.2)
    if out["trades"]:
        raise AssertionError("short trail updated and stopped on the same later bar")

    # One long winner: scale and same-bar trail, fee on entry plus two exit fills.
    bars = [bar(0, 100, 100, 100, 100), bar(1, 100.2, 101.0, 100.5, 100.8)]
    out = run_backtest(bars, [1, 0], 1.0, trade_margin=0.2)
    trade = out["trades"][0]
    target = 100.0 * (1.0 + TARGET_PCT)
    trail = 101.0 * (1.0 - TRAIL_PCT)
    notional = LEVERAGE * 0.2
    gross = 0.5 * notional * (target - 100.0) / 100.0 + 0.5 * notional * (trail - 100.0) / 100.0
    fees = FEE * notional + FEE * notional * 0.5 + FEE * notional * 0.5
    if not _approx(trade["gross_pnl"], gross) or not _approx(trade["fees"], fees):
        raise AssertionError("scale-out fee or pnl accounting is wrong")

    # No pyramid.
    bars = [bar(0, 100, 100, 100, 100), bar(1, 100, 100.2, 100, 100.1), bar(2, 100, 100, 100, 100)]
    out = run_backtest(bars, [1, 1, 0], 1.0, trade_margin=0.2)
    if out["entries"] != 1:
        raise AssertionError("pyramided")

    print("SELF_CHECK_OK", flush=True)


def assess_walk_forward(bars: list[dict], signals: list[int]) -> dict:
    """Locked-rule walk-forward. Parameters are not re-optimized.

    Skill shape for an intraday system: in-sample 6 to 12 months, out-of-sample
    1 to 3 months, step about 1 month. This uses the short end, 6 months and
    1 month. House rule: at least 3 out-of-sample windows and at least 30
    trades in each. WFE is OOS Sharpe / IS Sharpe of the same locked rules.
    """
    is_ms = int(round((365.25 / 2.0) * 86_400_000))
    oos_ms = int(round((365.25 / 12.0) * 86_400_000))
    plan = {
        "intraday_is": "6 to 12 months; the test uses 6 months, the short end of the skill",
        "intraday_oos": "1 to 3 months; the test uses 1 month",
        "step": "about 1 month",
        "house_min_oos_windows": 3,
        "min_trades_per_oos_window": 30,
        "reoptimize_parameters": False,
        "wfe_definition": (
            "out-of-sample close-path Sharpe divided by in-sample close-path Sharpe "
            "of the same locked rules, not a parameter search"
        ),
    }
    if len(bars) < 2:
        return {
            "satisfied": False,
            "this_run": "smoke test",
            "plan": plan,
            "span_days": "not computed",
            "windows_that_fit": 0,
            "valid_oos_windows": 0,
            "wfe": "not computed",
            "why_not_satisfied": "no bars",
        }
    t0 = int(bars[0]["close_time_ms"])
    t1 = int(bars[-1]["close_time_ms"])
    span_days = (t1 - t0) / 86_400_000.0
    available = 0
    cursor = t0
    while cursor + is_ms + oos_ms <= t1:
        available += 1
        cursor += oos_ms
        if available > 36:
            break
    report = {
        "satisfied": False,
        "this_run": "smoke test of locked rules on the fetched window",
        "plan": plan,
        "span_days": span_days,
        "windows_that_fit": available,
        "valid_oos_windows": 0,
        "wfe": "not computed",
    }
    if available < 3:
        report["why_not_satisfied"] = (
            f"The tradable 5m window spans {span_days:.4f} days. "
            "The intraday plan needs an in-sample window of 6 to 12 months and at least three "
            "out-of-sample windows of 1 to 3 months, stepped by about a month, each with at least 30 trades. "
            f"Using the short end (6 months in-sample, 1 month out-of-sample), {available} window(s) fit. "
            "A valid walk-forward test is not possible on this history. WFE was not computed. "
            "This run is a smoke test, not a walk-forward result."
        )
        return report

    window_rows = []
    cursor = t0
    while cursor + is_ms + oos_ms <= t1 and len(window_rows) < 36:
        is_hi = cursor + is_ms
        oos_hi = is_hi + oos_ms
        is_idx = [i for i, b in enumerate(bars) if cursor <= int(b["close_time_ms"]) < is_hi]
        oos_idx = [i for i, b in enumerate(bars) if is_hi <= int(b["close_time_ms"]) < oos_hi]

        def _run(idxs: list[int]):
            if not idxs:
                return None
            return run_backtest([bars[i] for i in idxs], [int(signals[i]) for i in idxs], INITIAL_EQUITY)

        is_run = _run(is_idx)
        oos_run = _run(oos_idx)
        is_sh = None if is_run is None else sharpe_from_close_path(is_run["close_path"])
        oos_sh = None if oos_run is None else sharpe_from_close_path(oos_run["close_path"])
        window_rows.append(
            {
                "is_trades": 0 if is_run is None else len(is_run["trades"]),
                "oos_trades": 0 if oos_run is None else len(oos_run["trades"]),
                "is_sharpe": None if is_sh is None else is_sh["net_sharpe_annualized"],
                "oos_sharpe": None if oos_sh is None else oos_sh["net_sharpe_annualized"],
            }
        )
        cursor += oos_ms
    valid = [
        row
        for row in window_rows
        if row["oos_trades"] >= 30
        and isinstance(row["is_sharpe"], float)
        and isinstance(row["oos_sharpe"], float)
        and row["is_sharpe"] > 0.0
    ]
    report["windows"] = window_rows
    report["valid_oos_windows"] = len(valid)
    report["this_run"] = "locked-rule windows evaluated; parameters were not re-optimized"
    if len(valid) < 3:
        report["why_not_satisfied"] = (
            f"{len(window_rows)} calendar windows fit, and {len(valid)} of them have at least 30 "
            "out-of-sample trades plus a positive in-sample Sharpe. The house minimum is 3. "
            "WFE was not computed."
        )
        return report
    ratios = [row["oos_sharpe"] / row["is_sharpe"] for row in valid]
    report["satisfied"] = True
    report["wfe"] = float(sum(ratios) / len(ratios))
    report["wfe_per_valid_window"] = ratios
    report["why_not_satisfied"] = None
    return report


def main() -> int:
    self_check()
    OUT.mkdir(parents=True, exist_ok=True)
    fetched_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    try:
        end_ms = fetched_at_ms
        meta_5m, raw_5m = fetch_binance_klines(
            "5m", int(SIX_MONTH_5M_START.timestamp() * 1000), end_ms, fetched_at_ms
        )
        (OUT / "btc_5m_raw.json").write_bytes(raw_5m)
        meta_1h, raw_1h = fetch_binance_klines(
            "1h", int(SIX_MONTH_1H_START.timestamp() * 1000), end_ms, fetched_at_ms
        )
        (OUT / "btc_1h_raw.json").write_bytes(raw_1h)
    except RuntimeError as exc:
        print(f"BACKTEST_DID_NOT_RUN {exc}", file=sys.stderr)
        return 1

    try:
        m5, info_5m = load_candles(raw_5m, "5m", 300_000, fetched_at_ms)
        h1, info_1h = load_candles(raw_1h, "1h", 3_600_000, fetched_at_ms)
    except RuntimeError as exc:
        print(f"BACKTEST_DID_NOT_RUN {exc}", file=sys.stderr)
        return 1

    if info_5m["coin_values"] not in ([], ["BTC"]) or info_1h["coin_values"] not in ([], ["BTC"]):
        print("BACKTEST_DID_NOT_RUN coin field is not BTC", file=sys.stderr)
        return 1

    hour_ema = compute_ema(h1["c"].to_numpy(dtype=float))
    # Numerical guard: pandas alpha must match 2/201 on this series' first step.
    if len(hour_ema) >= 2:
        manual = (1.0 - EMA_ALPHA) * float(h1["c"].iloc[0]) + EMA_ALPHA * float(h1["c"].iloc[1])
        if abs(float(hour_ema[1]) - manual) > 1e-6:
            print("BACKTEST_DID_NOT_RUN EMA recursion does not match alpha 2/201", file=sys.stderr)
            return 1

    hour_close_ms = h1["close_time_ms"].to_numpy(dtype=np.int64)
    m5 = m5.copy()
    m5["hour_index"] = [aligned_hour_index(hour_close_ms, int(ts)) for ts in m5["close_time_ms"].tolist()]

    warmup_dropped = 0
    hour_idx = m5["hour_index"].to_numpy(dtype=int)
    for idx in hour_idx.tolist():
        if idx >= EMA_SPAN - 1:
            break
        warmup_dropped += 1
    else:
        print(
            "BACKTEST_DID_NOT_RUN 1h history never covers 200 closed hours before a 5m bar",
            file=sys.stderr,
        )
        return 1

    tradable = m5.iloc[warmup_dropped:].reset_index(drop=True)
    # Indicators are computed on every closed 5m bar, then the book starts at the
    # first bar whose 1h EMA is defined. Dropped bars stay in the Donchian lookback.
    h_close = h1["c"].to_numpy(dtype=float)
    close_all = m5["c"].to_numpy(dtype=float)
    high_all = m5["h"].to_numpy(dtype=float)
    low_all = m5["l"].to_numpy(dtype=float)
    volume_all = m5["v"].to_numpy(dtype=float)
    hour_all = m5["hour_index"].to_numpy(dtype=int)
    full_sig_all = build_signals(close_all, high_all, low_all, volume_all, hour_all, h_close, hour_ema, True, True)
    no_volume_all = build_signals(close_all, high_all, low_all, volume_all, hour_all, h_close, hour_ema, False, True)
    no_ema_all = build_signals(close_all, high_all, low_all, volume_all, hour_all, h_close, hour_ema, True, False)
    full_sig = full_sig_all[warmup_dropped:]

    bars = [
        {
            "close_time_ms": int(row.close_time_ms),
            "o": float(row.o),
            "h": float(row.h),
            "l": float(row.l),
            "c": float(row.c),
        }
        for row in tradable.itertuples(index=False)
    ]
    result = run_backtest(bars, [int(s) for s in full_sig.tolist()], INITIAL_EQUITY)
    walk_forward = assess_walk_forward(bars, [int(s) for s in full_sig.tolist()])
    trades = result["trades"]
    trade_rets = [float(t["net_return_on_equity"]) for t in trades]
    trade_stats = mean_std_t(trade_rets)
    wins = sum(1 for t in trades if t["net_pnl"] > 0.0)
    losses = sum(1 for t in trades if t["net_pnl"] < 0.0)
    flats = sum(1 for t in trades if t["net_pnl"] == 0.0)

    mark_equities = [float(m["equity"]) for m in result["marks"]]
    dd_path = max_drawdown(mark_equities)
    # Close path is start equity plus one end-of-bar equity per tradable bar.
    dd_close = max_drawdown(result["close_path"])
    if abs(dd_path - max_drawdown(mark_equities)) > 1e-15:
        raise RuntimeError("drawdown recomputation failed")

    sharpe = sharpe_from_close_path(result["close_path"])
    n_trades = len(trades)
    span_days = walk_forward["span_days"] if isinstance(walk_forward["span_days"], float) else 0.0
    few_weeks = span_days < 60.0
    sharpe_is_qualification = bool(
        sharpe["net_sharpe_computed"]
        and n_trades >= 30
        and not few_weeks
        and walk_forward["satisfied"]
    )
    if n_trades < 30:
        sharpe_qualification_note = (
            f"closed trade count is {n_trades}, below 30. "
            "The annualized Sharpe is not a qualification statistic."
        )
    elif not sharpe["net_sharpe_computed"]:
        sharpe_qualification_note = "Sharpe was not computed, so it is not a qualification statistic."
    elif few_weeks:
        sharpe_qualification_note = (
            f"Trade count is {n_trades}, but the tradable window is {span_days:.4f} days. "
            "A few weeks is not enough for the annualized Sharpe to be a qualification statistic."
        )
    else:
        sharpe_qualification_note = (
            "Trade count is at least 30 and the window is longer than 60 days, "
            "but the locked-rule walk-forward did not produce 3 out-of-sample windows. "
            "The annualized Sharpe is not a qualification statistic."
        )

    sample_bars = int(len(tradable))
    sample_years = sample_bars / BARS_PER_YEAR
    if sample_years > 0.0:
        min_detectable = 1.96 / math.sqrt(sample_years)
    else:
        min_detectable = "not computed"

    full_diag = diagnostic_block(close_all, full_sig_all, "full_signal")
    vol_diag = diagnostic_block(close_all, no_volume_all, "drop_volume_filter")
    ema_diag = diagnostic_block(close_all, no_ema_all, "drop_ema_filter")
    full_mean = full_diag["overlapping"]["mean_net_20bar"]
    vol_flip = sign_flip(full_mean, vol_diag["overlapping"]["mean_net_20bar"])
    ema_flip = sign_flip(full_mean, ema_diag["overlapping"]["mean_net_20bar"])

    nonoverlap_t = full_diag["non_overlapping"]["t_stat"]
    t_gate = isinstance(nonoverlap_t, float) and nonoverlap_t >= 2.0

    final_mtm = (
        result["open_trade"]["mtm_equity"] if result["open_trade"] is not None else result["final_equity_realized"]
    )
    equity_multiple_realized = result["final_equity_realized"] / INITIAL_EQUITY
    equity_multiple_mtm = final_mtm / INITIAL_EQUITY

    house_sharpe_pass = bool(
        sharpe_is_qualification
        and isinstance(sharpe.get("net_sharpe_annualized"), float)
        and sharpe["net_sharpe_annualized"] > 1.0
    )
    dd_gate = dd_path >= -0.20

    # Deploy gates that this sample cannot support are failed, not waived into paper trade.
    gates = {
        "house_signal_t_stat_ge_2": {
            "pass": t_gate,
            "statistic": nonoverlap_t if isinstance(nonoverlap_t, float) else "not computed",
            "statistic_used": "non-overlapping signal diagnostic t-stat",
            "bar": 2.0,
        },
        "house_walk_forward_at_least_3_oos_windows": {
            "pass": bool(walk_forward["satisfied"]),
            "valid_oos_windows": walk_forward["valid_oos_windows"],
            "windows_that_fit": walk_forward["windows_that_fit"],
            "reason": walk_forward["why_not_satisfied"],
        },
        "house_net_sharpe_gt_1_after_costs": {
            "pass": house_sharpe_pass,
            "net_sharpe_annualized": sharpe["net_sharpe_annualized"],
            "is_qualification_statistic": sharpe_is_qualification,
            "note": sharpe_qualification_note,
        },
        "house_max_drawdown_le_20pct": {
            "pass": dd_gate,
            "max_drawdown": dd_path,
            "basis": "pessimistic intrabar path in equity.csv",
        },
        "deploy_adjusted_sharpe_gt_0.8": {
            "pass": False,
            "adjusted_sharpe": "not computed",
            "reason": (
                "not computed because the tradable history is under a year"
                if sample_years < 1.0
                else "not computed"
            ),
        },
        "deploy_dsr_significant_p_lt_0.05": {
            "pass": False,
            "deflated_sharpe": "not computed",
            "reason": (
                "not computed because there is no qualification Sharpe on a multi-year sample"
                if sample_years < 1.0 or not sharpe_is_qualification
                else "not computed"
            ),
        },
        "deploy_wfe_gt_0.6": {
            "pass": isinstance(walk_forward["wfe"], float) and walk_forward["wfe"] > 0.6,
            "wfe": walk_forward["wfe"],
            "reason": walk_forward["why_not_satisfied"],
        },
        "deploy_cpcv_paths_profitable_gt_80pct": {
            "pass": False,
            "cpcv": "not computed",
            "reason": "sample cannot form purged combinatorial paths with 30 trades each",
        },
    }
    decision = "GO" if all(g["pass"] for g in gates.values()) else "NO-GO"

    summary = {
        "decision": decision,
        "decision_note": (
            "NO-GO is required when any house bar or any deploy gate is unmet. "
            "Missing history is not a paper-trade approval. This script does not approve live trading."
        ),
        "script": str(SCRIPT_PATH),
        "summary_path": str(OUT / "summary.json"),
        "trades_path": str(OUT / "trades.csv"),
        "equity_path": str(OUT / "equity.csv"),
        "raw_5m_path": str(OUT / "btc_5m_raw.json"),
        "raw_1h_path": str(OUT / "btc_1h_raw.json"),
        "host": BINANCE_KLINES,
        "venue": "Binance USD-M BTCUSDT perpetual public klines",
        "venue_note": meta_5m.get("why_not_hyperliquid"),
        "fee_rate": FEE,
        "fee_note": (
            "0.045% of notional, carried from the Hyperliquid base taker schedule in "
            "userfees_zero_schedule.json. Binance's own fee schedule was not loaded. "
            "The author's 0.04% VIP rate was not used."
        ),
        "leverage": LEVERAGE,
        "notional_rule": (
            "notional = 0.01 * current equity / 0.007, so the 0.7% stop risks 1% of "
            "equity before fees. Margin posted = notional / 20. The book flattens and "
            "stays flat after equity falls 20% from its peak."
        ),
        "initial_equity": INITIAL_EQUITY,
        "trade_margin": None,
        "risk_fraction": RISK_FRACTION,
        "max_drawdown_halt": MAX_DRAWDOWN_HALT,
        "FUNDING": "NOT_APPLIED",
        "CPI_FOMC_CALENDAR": "NOT_APPLIED",
        "LIQUIDATION_MODEL": "NOT_APPLIED",
        "SPREAD_SLIPPAGE": "NOT_APPLIED",
        "volume_unit": "BTC base size, Binance kline field 5",
        "volume_field": "v",
        "post_only_fills": "not verified; research fill is the signal 5m close and the taker fee is charged",
        "maintenance_margin": "unknown",
        "isolated_hard_stop": "unverified",
        "parameters_searched": False,
        "variants_not_run": ["15m timeframe", "1.4% full target", "maker fee", "author 0.04% VIP taker"],
        "data": {
            "fetch_5m": meta_5m,
            "fetch_1h": meta_1h,
            "info_5m": info_5m,
            "info_1h": info_1h,
            "range_5m_open_utc": info_5m["first_open_utc"],
            "range_5m_last_close_utc": info_5m["last_close_utc"],
            "range_1h_open_utc": info_1h["first_open_utc"],
            "range_1h_last_close_utc": info_1h["last_close_utc"],
            "bars_5m_raw": info_5m["raw_count"],
            "bars_5m_closed": info_5m["closed_count"],
            "bars_1h_raw": info_1h["raw_count"],
            "bars_1h_closed": info_1h["closed_count"],
            "warmup_bars_dropped": warmup_dropped,
            "warmup_rule": "leading 5m bars dropped until the latest closed 1h bar at that 5m close is at least the 200th closed 1h bar",
            "tradable_5m_bars": sample_bars,
            "tradable_first_close_utc": utc_iso(int(tradable["close_time_ms"].iloc[0])),
            "tradable_last_close_utc": utc_iso(int(tradable["close_time_ms"].iloc[-1])),
            "outliers_5m": outlier_count(m5["c"].to_numpy(dtype=float)),
            "timestamp_convention": "t treated as open time. 5m close = t+5m. 1h close = t+1h. Forming bars with close time after the fetch timestamp were dropped.",
        },
        "fees": {
            "rate_per_fill": FEE,
            "charged_on": "entry notional and each exit fill's closed notional",
            "total_fees_closed_trades": float(sum(t["fees"] for t in trades)),
            "total_gross_pnl_closed_trades": float(sum(t["gross_pnl"] for t in trades)),
            "total_net_pnl_closed_trades": float(sum(t["net_pnl"] for t in trades)),
        },
        "trades": {
            "closed_trade_count": n_trades,
            "win_count": wins,
            "loss_count": losses,
            "flat_count": flats,
            "entries": result["entries"],
            "signals_skipped_because_in_position": result["signals_skipped_because_in_position"],
            "signals_skipped_insufficient_cash": result["signals_skipped_insufficient_cash"],
            "signals_skipped_drawdown_halt": result["signals_skipped_drawdown_halt"],
            "drawdown_halted": result["halted"],
            "open_trade_at_end": result["open_trade"],
            "ruined": result["ruined"],
            "per_trade_mean_net_return_on_equity": trade_stats["mean"],
            "per_trade_t_stat": trade_stats["t_stat"],
            "per_trade_t_stat_reason": trade_stats["reason"],
            "per_trade_definition": "net pnl including fees, divided by equity at that trade's entry. Not annualized.",
        },
        "performance": {
            "net_equity_multiple_realized": equity_multiple_realized,
            "total_return_realized": equity_multiple_realized - 1.0,
            "net_equity_multiple_mtm": equity_multiple_mtm,
            "total_return_mtm": equity_multiple_mtm - 1.0,
            "mtm_note": "realized multiple ignores an open trade; mtm marks it at the last 5m close",
            "max_drawdown": dd_path,
            "max_drawdown_close_path": dd_close,
            "max_drawdown_definition": (
                "Ordered marks in equity.csv. Entry bar: post-fee equity at the signal close only. "
                "Exit bar: the open, then each fill at the price the rule books. A print beyond the fill is not marked. "
                "Hold bar: open, favorable print, adverse print, then close. Favorable is ordered before adverse "
                "because the intrabar sequence is unknown. "
                "max_drawdown_close_path uses only start equity and one end-of-bar equity per bar."
            ),
            "net_sharpe": sharpe,
            "net_sharpe_is_qualification_statistic": sharpe_is_qualification,
            "net_sharpe_qualification_note": sharpe_qualification_note,
        },
        "signal_diagnostic": {
            "full": full_diag,
            "this_is_not_the_managed_trade_result": True,
            "ablation_drop_volume_filter_sign_flips_vs_full": vol_flip,
            "ablation_drop_ema_filter_sign_flips_vs_full": ema_flip,
            "ablation_note": (
                "Sign uses the overlapping all-events mean of each rule on the bars where that rule's own inputs exist. "
                "A flip is reported and not selected. Means are stored so the sign can be checked."
            ),
            "ablation_drop_volume": {
                "n": vol_diag["overlapping"]["n"],
                "mean_net_20bar": vol_diag["overlapping"]["mean_net_20bar"],
                "sign_flips": vol_flip,
            },
            "ablation_drop_ema": {
                "n": ema_diag["overlapping"]["n"],
                "mean_net_20bar": ema_diag["overlapping"]["mean_net_20bar"],
                "sign_flips": ema_flip,
            },
            "house_t_stat_gate_uses": "full signal, non-overlapping t-stat",
        },
        "walk_forward": walk_forward,
        "overfitting": {
            "locked_knob_count": 11,
            "locked_knobs": {
                "signal_timeframe": "5m",
                "donchian_lookback": DONCHIAN_N,
                "volume_lookback": VOL_N,
                "volume_multiple": VOL_MULT,
                "ema_timeframe": "1h",
                "ema_span": EMA_SPAN,
                "stop_pct": STOP_PCT,
                "target_pct": TARGET_PCT,
                "scale_fraction": SCALE_FRAC,
                "trail_pct": TRAIL_PCT,
                "leverage": LEVERAGE,
            },
            "prior_trials": PRIOR_TRIALS,
            "prior_trials_note": (
                "The author note already specified two timeframes (5m and 15m) and two exits "
                "(0.8% scale-out plus 0.3% trail, and the pseudocode 1.4% target). "
                "Those unused variants count as prior trials. This run did not search them. "
                "The stop was written as a 0.6% to 0.8% band; only the locked 0.7% was run."
            ),
            "expected_max_abs_z_under_null_for_n_trials": math.sqrt(2.0 * math.log(PRIOR_TRIALS)),
            "expected_max_z_note": (
                "sqrt(2*ln(N)) for N=4 prior written variants. "
                "Not applied to the smoke-test Sharpe, because that Sharpe is not a qualification statistic."
            ),
            "deflated_sharpe": "not computed",
            "deflated_sharpe_reason": "sample is a few weeks and there is no qualification Sharpe to deflate",
            "adjusted_sharpe": "not computed",
            "adjusted_sharpe_reason": "sample is a few weeks; autocorrelation and non-normality adjustments are not a deploy input",
            "minimum_backtest_length": "not computed",
            "minimum_backtest_length_reason": (
                "The skill states minimum backtest length in years. This history is a few weeks, "
                f"about {sample_years:.6f} years of tradable 5m bars ({sample_bars} bars / {BARS_PER_YEAR}). "
                "Under a normal approximation, an annualized Sharpe is distinguishable from zero at 95% "
                f"only if it exceeds about {min_detectable if isinstance(min_detectable, str) else round(min_detectable, 3)} "
                "on a sample of this length (1.96/sqrt(years)). A plausible Sharpe near the house bar of 1 "
                "cannot be distinguished from zero. The skill's multi-year examples were not used as measurements."
            ),
            "sample_years_tradable_5m": sample_years,
            "min_detectable_annualized_sharpe_95": min_detectable,
            "cpcv": "not computed",
            "pbo": "not computed",
            "monte_carlo": "not computed" if n_trades < 30 else "not computed",
            "monte_carlo_reason": (
                "fewer than 30 closed trades"
                if n_trades < 30
                else "sample is a few weeks; a resample of this window would not create the missing history"
            ),
            "parameter_sensitivity": "not run; the lock forbids a parameter search",
        },
        "gates": gates,
        "unverified": [
            "liquidation and maintenance margin",
            "funding pnl",
            "CPI and FOMC blackout",
            "spread and slippage beyond the pessimistic intrabar fill rules",
            "volume unit of field v",
            "post-only or maker fills",
            "whether an isolated stop exists on the venue before liquidation",
        ],
    }

    write_trades(OUT / "trades.csv", trades)
    write_equity(OUT / "equity.csv", result["marks"])
    # Recompute drawdown from the file that was just written.
    reread = []
    with (OUT / "equity.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            reread.append(float(row["equity"]))
    file_dd = max_drawdown(reread)
    if abs(file_dd - dd_path) > 1e-12:
        print("BACKTEST_DID_NOT_RUN equity.csv drawdown does not match the simulator", file=sys.stderr)
        return 1
    summary["performance"]["max_drawdown_reread_from_equity_csv"] = file_dd

    with (OUT / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    print(
        json.dumps(
            {
                "decision": decision,
                "trades": n_trades,
                "wins": wins,
                "losses": losses,
                "equity_multiple_realized": equity_multiple_realized,
                "max_drawdown": dd_path,
                "warmup_bars_dropped": warmup_dropped,
                "tradable_bars": sample_bars,
                "sharpe_computed": sharpe["net_sharpe_computed"],
                "sharpe_is_qualification_statistic": sharpe_is_qualification,
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
