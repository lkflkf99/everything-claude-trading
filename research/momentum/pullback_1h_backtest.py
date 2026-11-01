"""Locked 1H pullback test. One parameter set. No search.

Book A uses the unverified 1.5 bp maker / 4.0 bp taker stack.
Book B1 charges Hyperliquid base taker 4.5 bp on both legs.
Book B2 charges 2.0 / 5.0 bp and adds 2 bp adverse slippage on stops.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "pullback_1h"
BINANCE = "https://fapi.binance.com/fapi/v1/klines"
SYMBOL = "BTCUSDT"
HOUR_MS = 3_600_000
FOUR_MS = 14_400_000
EQUITY0 = 5_000.0
RISK = 0.0075
MIN_RISK = 0.003
MAX_LEV = 20.0
MIN_STOP = 40.0
RR = 1.5
K_STOP = 0.5
DD_HALT = 0.20
BARS_PER_YEAR = 365.25 * 24

BOOKS = {
    "A": {"maker": 0.00015, "taker": 0.00040, "stop_slip": 0.0, "label": "unverified maker 1.5bp / taker 4.0bp"},
    "B1": {"maker": 0.00045, "taker": 0.00045, "stop_slip": 0.0, "label": "Hyperliquid base taker 4.5bp both legs"},
    "B2": {"maker": 0.00020, "taker": 0.00050, "stop_slip": 0.0002, "label": "maker 2.0bp / taker 5.0bp, stop slip 2bp"},
}


def fetch(interval: str, start_ms: int, end_ms: int) -> list[dict]:
    step = HOUR_MS if interval == "1h" else FOUR_MS
    cursor = start_ms
    rows_out: list[dict] = []
    page = 0
    while cursor < end_ms:
        url = (
            f"{BINANCE}?symbol={SYMBOL}&interval={interval}"
            f"&startTime={cursor}&endTime={end_ms - 1}&limit=1500"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "pullback-1h-backtest"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                status = int(resp.status)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Binance {interval} HTTP {exc.code}: {exc.read()[:300]!r}") from exc
        payload = json.loads(raw)
        if isinstance(payload, dict):
            raise RuntimeError(f"Binance {interval} error: {payload}")
        if not payload:
            break
        page += 1
        print(f"BINANCE {interval} page {page} bars {len(payload)} status {status}", file=sys.stderr, flush=True)
        last_open = int(payload[-1][0])
        for row in payload:
            open_ms = int(row[0])
            if open_ms < cursor or open_ms >= end_ms:
                continue
            rows_out.append(
                {
                    "t": open_ms,
                    "T": int(row[6]),
                    "o": float(row[1]),
                    "h": float(row[2]),
                    "l": float(row[3]),
                    "c": float(row[4]),
                    "v": float(row[5]),
                }
            )
        nxt = last_open + step
        if nxt <= cursor:
            raise RuntimeError(f"{interval} page did not advance")
        cursor = nxt
        if len(payload) < 1500:
            break
    return rows_out


def load_or_fetch(interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"btc_{interval}_raw.json"
    if path.exists():
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        rows = fetch(interval, start_ms, end_ms)
        path.write_text(json.dumps(rows), encoding="utf-8")
    frame = pd.DataFrame(rows).drop_duplicates("t").sort_values("t").reset_index(drop=True)
    frame = frame.loc[frame["T"] <= end_ms].reset_index(drop=True)
    return frame


def wilder_atr(frame: pd.DataFrame) -> pd.Series:
    prev = frame["c"].shift(1)
    tr = pd.concat([(frame["h"] - frame["l"]).abs(), (frame["h"] - prev).abs(), (frame["l"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False).mean()


def average_tie_percentile(values: np.ndarray, window: int, min_periods: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    for i in range(min_periods - 1, len(values)):
        start = max(0, i - window + 1)
        sample = values[start : i + 1]
        last = sample[-1]
        less = int(np.count_nonzero(sample < last))
        equal = int(np.count_nonzero(sample == last))
        out[i] = (less + (equal + 1) / 2.0) / sample.size
    return out


def prepare(h1: pd.DataFrame, h4: pd.DataFrame) -> pd.DataFrame:
    x = h1.copy()
    x["ema20"] = x["c"].ewm(span=20, adjust=False).mean()
    x["atr"] = wilder_atr(x)
    typical = (x["h"] + x["l"] + x["c"]) / 3.0
    volume = x["v"].replace(0, np.nan)
    x["vwap"] = (typical * volume).rolling(24, min_periods=12).sum() / volume.rolling(24, min_periods=12).sum()
    x["atr_pct"] = average_tie_percentile(x["atr"].to_numpy(dtype=float), 720, 360)
    h = h4.copy()
    h["ema20"] = h["c"].ewm(span=20, adjust=False).mean()
    h["ema50"] = h["c"].ewm(span=50, adjust=False).mean()
    ready = np.arange(len(h)) >= 49
    regime = np.zeros(len(h), dtype=int)
    long_reg = ready & (h["ema20"].to_numpy() > h["ema50"].to_numpy()) & (h["c"].to_numpy() > h["ema50"].to_numpy())
    short_reg = ready & (h["ema20"].to_numpy() < h["ema50"].to_numpy()) & (h["c"].to_numpy() < h["ema50"].to_numpy())
    regime[long_reg] = 1
    regime[short_reg] = -1
    aligned = np.searchsorted(h["T"].to_numpy(dtype=np.int64), x["T"].to_numpy(dtype=np.int64), side="right") - 1
    x["regime"] = 0
    valid = aligned >= 0
    x.loc[valid, "regime"] = regime[aligned[valid]]
    return x


def rejection(side: int, o: float, h: float, l: float, c: float) -> bool:
    body = abs(c - o)
    if side > 0:
        return c > o or (min(o, c) - l) >= body
    return c < o or (h - max(o, c)) >= body


def in_band(side: int, close: float, anchor: float, atr: float) -> bool:
    if not np.isfinite(anchor) or not np.isfinite(atr):
        return False
    if side > 0:
        return anchor - 0.15 * atr <= close <= anchor + 0.10 * atr
    return anchor - 0.10 * atr <= close <= anchor + 0.15 * atr


def signal_side(frame: pd.DataFrame, i: int) -> int:
    row = frame.iloc[i]
    regime = int(row["regime"])
    if regime == 0 or not np.isfinite(row["atr_pct"]) or not np.isfinite(row["atr"]) or not np.isfinite(row["vwap"]):
        return 0
    if not (0.35 <= float(row["atr_pct"]) <= 0.90):
        return 0
    side = regime
    close = float(row["c"])
    atr = float(row["atr"])
    ema = float(row["ema20"])
    vwap = float(row["vwap"])
    if not (in_band(side, close, ema, atr) or in_band(side, close, vwap, atr)):
        return 0
    if i < 23:
        return 0
    prior_c = frame["c"].iloc[i - 23 : i].to_numpy(dtype=float)
    prior_v = frame["vwap"].iloc[i - 23 : i].to_numpy(dtype=float)
    if side > 0 and not np.any(prior_c > prior_v):
        return 0
    if side < 0 and not np.any(prior_c < prior_v):
        return 0
    if side > 0 and float(row["l"]) < vwap - 0.25 * atr:
        return 0
    if side < 0 and float(row["h"]) > vwap + 0.25 * atr:
        return 0
    if not rejection(side, float(row["o"]), float(row["h"]), float(row["l"]), close):
        return 0
    return side


def worsen(side: int, price: float, slip: float) -> float:
    if slip == 0.0:
        return price
    return price * (1 - slip) if side > 0 else price * (1 + slip)


def simulate(frame: pd.DataFrame, start_ms: int, end_ms: int, maker: float, taker: float, stop_slip: float) -> dict:
    cash = EQUITY0
    peak = EQUITY0
    pos = None
    pending = None
    halted = False
    fills_on_day: dict[str, int] = {}
    blocked: dict[int, str] = {}
    trades = []
    marks = []
    opens = frame["t"].to_numpy(dtype=np.int64)
    closes = frame["T"].to_numpy(dtype=np.int64)
    for i in range(len(frame) - 1):
        row = frame.iloc[i]
        o, h, l, c = float(row["o"]), float(row["h"]), float(row["l"]), float(row["c"])
        atr = float(row["atr"]) if np.isfinite(row["atr"]) else np.nan
        day = datetime.fromtimestamp(opens[i] / 1000, timezone.utc).strftime("%Y-%m-%d")
        if pos is not None and i > pos["fill_i"]:
            exit_px, reason = None, None
            if pos["side"] > 0:
                if o <= pos["stop"]:
                    exit_px, reason = worsen(1, o, stop_slip), "STOP_GAP"
                elif l <= pos["stop"]:
                    exit_px, reason = worsen(1, pos["stop"], stop_slip), "STOP"
                elif h >= pos["tp"]:
                    exit_px, reason = pos["tp"], "TP"
            else:
                if o >= pos["stop"]:
                    exit_px, reason = worsen(-1, o, stop_slip), "STOP_GAP"
                elif h >= pos["stop"]:
                    exit_px, reason = worsen(-1, pos["stop"], stop_slip), "STOP"
                elif l <= pos["tp"]:
                    exit_px, reason = pos["tp"], "TP"
            if exit_px is not None:
                gross = pos["side"] * pos["qty"] * (exit_px - pos["entry"])
                exit_fee = pos["qty"] * exit_px * taker
                cash += gross - exit_fee
                trades.append(
                    {
                        "side": pos["side"],
                        "entry_ms": int(opens[pos["fill_i"]]),
                        "exit_ms": int(closes[i]),
                        "hold_bars": i - pos["fill_i"],
                        "entry": pos["entry"],
                        "exit": exit_px,
                        "reason": reason,
                        "qty": pos["qty"],
                        "gross": gross,
                        "fees": pos["entry_fee"] + exit_fee,
                        "net": gross - pos["entry_fee"] - exit_fee,
                        "notional": pos["qty"] * pos["entry"],
                        "risk_bps": pos["risk_bps"],
                        "equity_after": cash,
                    }
                )
                pos = None
        if pending is not None and i == pending["rest_i"] and pos is None and not halted:
            side = pending["side"]
            limit = pending["limit"]
            filled = (side > 0 and l <= limit) or (side < 0 and h >= limit)
            if filled and fills_on_day.get(day, 0) < 2:
                stop = pending["stop"]
                exit_px, reason = None, None
                if side > 0:
                    if o <= stop:
                        exit_px, reason = worsen(1, o, stop_slip), "STOP_GAP"
                    elif l <= stop:
                        exit_px, reason = worsen(1, stop, stop_slip), "STOP"
                    elif h >= pending["tp"]:
                        exit_px, reason = pending["tp"], "TP"
                else:
                    if o >= stop:
                        exit_px, reason = worsen(-1, o, stop_slip), "STOP_GAP"
                    elif h >= stop:
                        exit_px, reason = worsen(-1, stop, stop_slip), "STOP"
                    elif l <= pending["tp"]:
                        exit_px, reason = pending["tp"], "TP"
                entry_fee = pending["qty"] * limit * maker
                cash -= entry_fee
                fills_on_day[day] = fills_on_day.get(day, 0) + 1
                if exit_px is None:
                    pos = {
                        "side": side,
                        "entry": limit,
                        "qty": pending["qty"],
                        "stop": stop,
                        "tp": pending["tp"],
                        "fill_i": i,
                        "entry_fee": entry_fee,
                        "risk_bps": pending["risk_bps"],
                    }
                else:
                    gross = side * pending["qty"] * (exit_px - limit)
                    exit_fee = pending["qty"] * exit_px * taker
                    cash += gross - exit_fee
                    trades.append(
                        {
                            "side": side,
                            "entry_ms": int(opens[i]),
                            "exit_ms": int(closes[i]),
                            "hold_bars": 0,
                            "entry": limit,
                            "exit": exit_px,
                            "reason": reason,
                            "qty": pending["qty"],
                            "gross": gross,
                            "fees": entry_fee + exit_fee,
                            "net": gross - entry_fee - exit_fee,
                            "notional": pending["qty"] * limit,
                            "risk_bps": pending["risk_bps"],
                            "equity_after": cash,
                        }
                    )
            elif not filled and np.isfinite(atr):
                toxic = (side > 0 and c < limit - 0.5 * atr) or (side < 0 and c > limit + 0.5 * atr)
                if toxic:
                    blocked[side] = day
            pending = None
        mtm = cash if pos is None else cash + pos["side"] * pos["qty"] * (c - pos["entry"])
        if mtm > peak:
            peak = mtm
        marks.append((int(closes[i]), mtm))
        if (not halted) and peak > 0 and (mtm / peak - 1.0) <= -DD_HALT:
            if pos is not None:
                gross = pos["side"] * pos["qty"] * (c - pos["entry"])
                exit_fee = pos["qty"] * c * taker
                cash += gross - exit_fee
                trades.append(
                    {
                        "side": pos["side"],
                        "entry_ms": int(opens[pos["fill_i"]]),
                        "exit_ms": int(closes[i]),
                        "hold_bars": i - pos["fill_i"],
                        "entry": pos["entry"],
                        "exit": c,
                        "reason": "DD_HALT",
                        "qty": pos["qty"],
                        "gross": gross,
                        "fees": pos["entry_fee"] + exit_fee,
                        "net": gross - pos["entry_fee"] - exit_fee,
                        "notional": pos["qty"] * pos["entry"],
                        "risk_bps": pos["risk_bps"],
                        "equity_after": cash,
                    }
                )
                pos = None
                mtm = cash
                marks[-1] = (int(closes[i]), mtm)
            halted = True
        if halted or pos is not None or pending is not None:
            continue
        if not (start_ms <= int(closes[i]) < end_ms):
            continue
        if i + 1 >= len(frame) or int(opens[i + 1]) != int(opens[i]) + HOUR_MS:
            continue
        side = signal_side(frame, i)
        if side == 0 or blocked.get(side) == day:
            continue
        ema = float(row["ema20"])
        vwap = float(row["vwap"])
        limit = min(ema, vwap) if side > 0 else max(ema, vwap)
        extreme = float(row["l"]) if side > 0 else float(row["h"])
        if side > 0:
            stop = min(extreme, limit) - K_STOP * atr
            tp = limit + RR * (limit - stop)
        else:
            stop = max(extreme, limit) + K_STOP * atr
            tp = limit - RR * (stop - limit)
        dist = abs(limit - stop)
        risk_bps = dist / limit * 1e4
        if risk_bps < MIN_STOP or dist <= 0 or not np.isfinite(limit):
            continue
        qty = cash * RISK / dist
        if qty * limit / cash > MAX_LEV:
            qty = cash * MAX_LEV / limit
        if qty * dist < cash * MIN_RISK or qty <= 0:
            continue
        pending = {
            "side": side,
            "limit": limit,
            "stop": stop,
            "tp": tp,
            "qty": qty,
            "rest_i": i + 1,
            "risk_bps": risk_bps,
        }
    if pos is not None:
        # Still open at the last completed loop bar. Leave it marked, not invented flat.
        pass
    return {"trades": trades, "marks": marks, "equity": cash if pos is None else None, "halted": halted, "open": pos is not None}


def sharpe(marks: list[tuple[int, float]], start_ms: int, end_ms: int) -> dict:
    path = [equity for ts, equity in marks if start_ms <= ts < end_ms]
    if len(path) < 3:
        return {"net_sharpe_annualized": None, "reason": "fewer than 3 marks"}
    equity = np.asarray(path, dtype=float)
    prev = equity[:-1]
    ret = np.divide(np.diff(equity), prev, out=np.zeros(len(prev)), where=prev != 0)
    std = float(ret.std(ddof=1))
    if std == 0.0:
        return {"net_sharpe_annualized": None, "reason": "zero variance"}
    return {
        "net_sharpe_annualized": float(ret.mean() / std * np.sqrt(BARS_PER_YEAR)),
        "bar_n": int(ret.size),
        "reason": None,
    }


def max_dd(marks: list[tuple[int, float]], start_ms: int, end_ms: int) -> float | None:
    path = [EQUITY0] + [equity for ts, equity in marks if start_ms <= ts < end_ms]
    if len(path) < 2:
        return None
    equity = np.asarray(path, dtype=float)
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity / peak - 1.0))


def trade_stats(trades: list[dict]) -> dict:
    if not trades:
        return {
            "trades": 0,
            "win_rate": None,
            "mean_net_bps": None,
            "t_stat": None,
            "mean_hold_hours": None,
            "net_pnl": 0.0,
            "gross_pnl": 0.0,
            "fees": 0.0,
        }
    net_bps = np.asarray([t["net"] / t["notional"] * 1e4 for t in trades], dtype=float)
    n = len(net_bps)
    std = float(net_bps.std(ddof=1)) if n > 1 else None
    t_stat = None if std in (None, 0.0) else float(net_bps.mean() / (std / np.sqrt(n)))
    wins = sum(1 for t in trades if t["net"] > 0)
    return {
        "trades": n,
        "wins": wins,
        "win_rate": wins / n,
        "mean_net_bps": float(net_bps.mean()),
        "t_stat": t_stat,
        "mean_hold_hours": float(np.mean([t["hold_bars"] for t in trades])),
        "net_pnl": float(sum(t["net"] for t in trades)),
        "gross_pnl": float(sum(t["gross"] for t in trades)),
        "fees": float(sum(t["fees"] for t in trades)),
    }


def summarize_run(name: str, result: dict, start_ms: int, end_ms: int) -> dict:
    stats = trade_stats(result["trades"])
    stats["book"] = name
    stats["halted"] = result["halted"]
    stats["open_at_end"] = result["open"]
    stats["max_drawdown"] = max_dd(result["marks"], start_ms, end_ms)
    stats["sharpe"] = sharpe(result["marks"], start_ms, end_ms)
    stats["final_equity_if_flat"] = result["equity"]
    return stats


def ms(date_text: str) -> int:
    return int(datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc).timestamp() * 1000)


def self_check() -> None:
    t0 = 1_704_067_200_000
    raw = pd.DataFrame(
        {
            "t": [t0 + i * HOUR_MS for i in range(6)],
            "T": [t0 + (i + 1) * HOUR_MS - 1 for i in range(6)],
            "o": [100, 100, 100, 100, 100, 100],
            "h": [101, 101, 101, 110, 110, 110],
            "l": [99, 99, 94, 99, 99, 99],
            "c": [100.2, 100.2, 100.2, 100, 100, 100],
            "v": [1, 1, 1, 1, 1, 1],
        }
    )
    assert int(raw["t"].iloc[1]) - int(raw["t"].iloc[0]) == HOUR_MS
    assert rejection(1, 100.0, 101.0, 99.0, 100.2)
    assert rejection(-1, 100.2, 101.0, 99.0, 100.0)
    print("SELF_CHECK_OK", file=sys.stderr)


def main() -> None:
    self_check()
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = ms("2022-01-01T00:00:00")
    h1 = load_or_fetch("1h", start_ms, end_ms)
    h4 = load_or_fetch("4h", start_ms, end_ms)
    frame = prepare(h1, h4)
    print(
        f"bars_1h {len(h1)} first {datetime.fromtimestamp(int(h1['t'].iloc[0]) / 1000, timezone.utc)} "
        f"last_close {datetime.fromtimestamp(int(h1['T'].iloc[-1]) / 1000, timezone.utc)}",
        file=sys.stderr,
    )
    oos_windows = [
        ("2024-01-01", "2024-07-01"),
        ("2024-07-01", "2025-01-01"),
        ("2025-01-01", "2025-07-01"),
        ("2025-07-01", "2026-01-01"),
        ("2026-01-01", "2026-07-01"),
    ]
    is_windows = [
        ("2022-01-01", "2024-01-01"),
        ("2022-07-01", "2024-07-01"),
        ("2023-01-01", "2025-01-01"),
        ("2023-07-01", "2025-07-01"),
        ("2024-01-01", "2026-01-01"),
    ]
    concat_start = ms("2024-01-01T00:00:00")
    concat_end = int(frame["T"].iloc[-1]) + 1
    report = {"books": {}, "data": {"bars_1h": int(len(h1)), "bars_4h": int(len(h4))}}
    for name, cfg in BOOKS.items():
        concat = simulate(frame, concat_start, concat_end, cfg["maker"], cfg["taker"], cfg["stop_slip"])
        concat_stats = summarize_run(name, concat, concat_start, concat_end)
        windows = []
        wfes = []
        for (oos_a, oos_b), (is_a, is_b) in zip(oos_windows, is_windows):
            oos = simulate(frame, ms(oos_a + "T00:00:00"), ms(oos_b + "T00:00:00"), cfg["maker"], cfg["taker"], cfg["stop_slip"])
            ins = simulate(frame, ms(is_a + "T00:00:00"), ms(is_b + "T00:00:00"), cfg["maker"], cfg["taker"], cfg["stop_slip"])
            oos_stats = summarize_run(name, oos, ms(oos_a + "T00:00:00"), ms(oos_b + "T00:00:00"))
            is_stats = summarize_run(name, ins, ms(is_a + "T00:00:00"), ms(is_b + "T00:00:00"))
            oos_sh = oos_stats["sharpe"].get("net_sharpe_annualized")
            is_sh = is_stats["sharpe"].get("net_sharpe_annualized")
            wfe = None
            if oos_stats["trades"] >= 30 and is_sh is not None and is_sh > 0 and oos_sh is not None:
                wfe = oos_sh / is_sh
                wfes.append(wfe)
            windows.append(
                {
                    "oos": [oos_a, oos_b],
                    "oos_trades": oos_stats["trades"],
                    "oos_mean_net_bps": oos_stats["mean_net_bps"],
                    "oos_t": oos_stats["t_stat"],
                    "oos_hold_h": oos_stats["mean_hold_hours"],
                    "oos_sharpe": oos_sh,
                    "oos_dd": oos_stats["max_drawdown"],
                    "oos_halted": oos_stats["halted"],
                    "is_sharpe": is_sh,
                    "wfe": wfe,
                }
            )
        report["books"][name] = {
            "label": cfg["label"],
            "concat_oos": concat_stats,
            "windows": windows,
            "wfe_mean_defined": None if not wfes else float(np.mean(wfes)),
        }
        if name == "B1":
            pd.DataFrame(concat["trades"]).to_csv(OUT / "trades_b1_concat_oos.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    brief = {}
    for name, book in report["books"].items():
        c = book["concat_oos"]
        brief[name] = {
            "trades": c["trades"],
            "win_rate": c["win_rate"],
            "mean_net_bps": c["mean_net_bps"],
            "t_stat": c["t_stat"],
            "mean_hold_hours": c["mean_hold_hours"],
            "max_drawdown": c["max_drawdown"],
            "sharpe": c["sharpe"].get("net_sharpe_annualized"),
            "net_pnl": c["net_pnl"],
            "halted": c["halted"],
            "wfe_mean_defined": book["wfe_mean_defined"],
        }
    print(json.dumps({"bars_1h": report["data"]["bars_1h"], "books": brief}, indent=2))


if __name__ == "__main__":
    main()
