"""Locked BTC-USDT-SWAP backtest on OKX public data.

Rules are the pre-registered 365/30 time-series momentum spec.
This file downloads public candles and funding, then computes the path.
It does not place orders. The taker fee is the published Lv1 rate, not a
point-in-time historical schedule. Daily bars have no bid/ask.
"""

from __future__ import annotations

import csv
import io
import json
import math
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

INST = "BTC-USDT-SWAP"
BASE = "https://www.okx.com/api/v5"
ROOT = Path(__file__).resolve().parent / "data"
TAKER = 0.0005  # published OKX futures Lv1 taker, constant
TARGET_VOL = 0.10
L_MAX = 1.0
HALT_DD = 0.15
EQUITY0 = 10_000.0
LAG = 20
LIST_MS = 1573557408000  # 2019-11-12 11:16:48 UTC, instrument listTime
DAY_MS = 86_400_000
FOUR_H_MS = 4 * 3_600_000


def get_json(url: str, tries: int = 6) -> dict:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research-backtest"})
            with urllib.request.urlopen(req, timeout=40) as resp:
                body = json.load(resp)
            if str(body.get("code")) not in ("0", "None"):
                raise RuntimeError(body.get("msg") or body)
            return body
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.8 * (i + 1))
    raise RuntimeError(f"failed {url}: {last}")


def paginate(path: str, bar: str | None, ts_of, limit: int = 100, max_pages: int = 500) -> list:
    rows = []
    seen = set()
    after = None
    pages = 0
    while pages < max_pages:
        url = f"{BASE}/{path}?instId={INST}&limit={limit}"
        if bar:
            url += f"&bar={bar}"
        if after:
            url += f"&after={after}"
        batch = get_json(url).get("data") or []
        pages += 1
        if not batch:
            break
        added = 0
        oldest = None
        for rec in batch:
            ts = int(ts_of(rec))
            if ts in seen:
                continue
            seen.add(ts)
            rows.append(rec)
            added += 1
            oldest = ts if oldest is None else min(oldest, ts)
        if added == 0 or oldest is None:
            break
        after = str(oldest)
        if len(batch) < limit or oldest <= LIST_MS:
            break
        if pages % 20 == 0:
            print(f"  {path} {bar or 'funding'} pages={pages} rows={len(rows)}", flush=True)
        time.sleep(0.12)
    print(f"  done {path} {bar or 'funding'} pages={pages} rows={len(rows)}", flush=True)
    return rows


def utc_date(ms: int):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date()


def read_csv(path: Path) -> list:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_candles(path: Path, raw: list, confirm_index: int) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        fields = ["ts", "open", "high", "low", "close", "confirm"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        kept = 0
        for rec in sorted(raw, key=lambda r: int(r[0])):
            if len(rec) <= confirm_index or str(rec[confirm_index]) != "1":
                continue
            kept += 1
            w.writerow(
                {
                    "ts": rec[0],
                    "open": rec[1],
                    "high": rec[2],
                    "low": rec[3],
                    "close": rec[4],
                    "confirm": rec[confirm_index],
                }
            )
    print(f"  wrote {path.name} rows={kept}", flush=True)


def download_funding_rows() -> list[dict]:
    """Monthly OKX archive from 2022-03, plus the REST window for the newest settlements."""
    rates: dict[int, float] = {}
    mismatches = 0
    y, m = 2022, 3
    while (y, m) <= (2026, 11):
        stamp = f"{y}{m:02d}"
        url = (
            "https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/"
            f"{stamp}/BTC-USDT-SWAP-fundingrates-{y}-{m:02d}.zip"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "research-backtest"})
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                blob = resp.read()
        except urllib.error.HTTPError as exc:
            print(f"  funding zip {y}-{m:02d} HTTP {exc.code}", flush=True)
            m = 1 if m == 12 else m + 1
            y = y + 1 if m == 1 else y
            continue
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            name = zf.namelist()[0]
            text = zf.read(name).decode("utf-8")
        for row in csv.DictReader(io.StringIO(text)):
            ts = int(row["funding_time"])
            rate = float(row["funding_rate"])
            prev = rates.get(ts)
            if prev is not None and abs(prev - rate) > 1e-15:
                mismatches += 1
            rates[ts] = rate
        print(f"  funding zip {y}-{m:02d} total={len(rates)}", flush=True)
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
        time.sleep(0.05)
    rest = paginate("public/funding-rate-history", None, lambda r: r["fundingTime"])
    for rec in rest:
        ts = int(rec["fundingTime"])
        rate = float(rec["fundingRate"])
        prev = rates.get(ts)
        if prev is not None and abs(prev - rate) > 1e-12:
            mismatches += 1
        rates[ts] = rate
    print(f"  funding merged={len(rates)} rest_mismatches={mismatches}", flush=True)
    return [{"fundingTime": str(ts), "fundingRate": f"{rates[ts]:.16f}"} for ts in sorted(rates)]


def load_or_download() -> tuple:
    ROOT.mkdir(parents=True, exist_ok=True)
    daily_path = ROOT / "okx_btcusdt_swap_1d.csv"
    mark_path = ROOT / "okx_btcusdt_swap_mark_1d.csv"
    fund_path = ROOT / "okx_btcusdt_swap_funding.csv"
    m4_path = ROOT / "okx_btcusdt_swap_mark_4h.csv"

    if len(read_csv(daily_path)) < 1000:
        print("downloading trade candles", flush=True)
        trade = paginate("market/history-candles", "1Dutc", lambda r: r[0])
        write_candles(daily_path, trade, 8)
    if len(read_csv(mark_path)) < 1000:
        print("downloading daily marks", flush=True)
        mark = paginate("market/history-mark-price-candles", "1Dutc", lambda r: r[0])
        write_candles(mark_path, mark, 5)
    if len(read_csv(m4_path)) < 1000:
        print("downloading 4h marks", flush=True)
        mark4 = paginate("market/history-mark-price-candles", "4H", lambda r: r[0])
        write_candles(m4_path, mark4, 5)
    fund_rows = read_csv(fund_path)
    if len(fund_rows) < 3000:
        print("downloading funding archive", flush=True)
        fund_rows = download_funding_rows()
        with fund_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["fundingTime", "fundingRate"])
            w.writeheader()
            w.writerows(fund_rows)
    else:
        print("using cached OKX files", flush=True)
    return read_csv(daily_path), read_csv(mark_path), read_csv(fund_path), read_csv(m4_path)


def fnum(x: str) -> float:
    return float(x)


def build_panels(daily_rows, mark_rows, fund_rows, m4_rows):
    trade = {int(r["ts"]): r for r in daily_rows}
    mark = {int(r["ts"]): r for r in mark_rows}
    common = sorted(set(trade) & set(mark))
    missing_mark = sorted(set(trade) - set(mark))
    missing_trade = sorted(set(mark) - set(trade))
    days = []
    gaps = 0
    prev = None
    for ts in common:
        d = utc_date(ts)
        if prev is not None and (d - prev).days != 1:
            gaps += (d - prev).days - 1
        prev = d
        tr = trade[ts]
        mk = mark[ts]
        days.append(
            {
                "ts": ts,
                "date": d,
                "close_time": ts + DAY_MS,
                "px": fnum(tr["close"]),
                "mo": fnum(mk["open"]),
                "mh": fnum(mk["high"]),
                "ml": fnum(mk["low"]),
                "mc": fnum(mk["close"]),
            }
        )
    by_date = {d["date"]: i for i, d in enumerate(days)}
    fundings = [(int(r["fundingTime"]), fnum(r["fundingRate"])) for r in fund_rows]
    fundings.sort()
    marks4 = []
    for r in m4_rows:
        ts = int(r["ts"])
        marks4.append((ts + FOUR_H_MS, fnum(r["close"])))
    marks4.sort()
    return days, by_date, fundings, marks4, gaps, len(missing_mark), len(missing_trade)


def mark_asof(marks4: list, t: int) -> float | None:
    lo, hi = 0, len(marks4)
    while lo < hi:
        mid = (lo + hi) // 2
        if marks4[mid][0] <= t:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return None
    obs_t, px = marks4[lo - 1]
    if t - obs_t > FOUR_H_MS:
        return None
    return px


def sign_of(p_new: float, p_old: float) -> int:
    if p_new > p_old:
        return 1
    if p_new < p_old:
        return -1
    return 0


def prepare_signals(days, by_date):
    n = len(days)
    signal = [0] * n
    sigma = [None] * n
    eligible = [False] * n
    for i, day in enumerate(days):
        d = day["date"]
        d30 = d - timedelta(days=30)
        d395 = d - timedelta(days=395)
        if d30 in by_date and d395 in by_date:
            p30 = days[by_date[d30]]["px"]
            p395 = days[by_date[d395]]["px"]
            if p30 > 0 and p395 > 0:
                signal[i] = sign_of(p30, p395)
        rets = []
        ok = True
        for k in range(30):
            dk = d - timedelta(days=k)
            dprev = dk - timedelta(days=1)
            if dk not in by_date or dprev not in by_date:
                ok = False
                break
            p1 = days[by_date[dk]]["px"]
            p0 = days[by_date[dprev]]["px"]
            if p1 <= 0 or p0 <= 0:
                ok = False
                break
            rets.append(math.log(p1 / p0))
        if ok and len(rets) == 30:
            sigma[i] = math.sqrt((365.0 / 30.0) * sum(r * r for r in rets))
        eligible[i] = d395 in by_date and sigma[i] is not None and days[by_date[d395]]["px"] > 0 and (
            d30 in by_date and days[by_date[d30]]["px"] > 0
        )
    return signal, sigma, eligible


def newey_west_t(values: list[float], lag: int = LAG) -> dict:
    n = len(values)
    if n <= lag + 2:
        return {"n": n, "mean": None, "t": None, "reason": "too few observations"}
    mean = sum(values) / n
    demeaned = [v - mean for v in values]

    def gamma(k: int) -> float:
        return sum(demeaned[t] * demeaned[t - k] for t in range(k, n)) / n

    svar = gamma(0)
    for k in range(1, lag + 1):
        svar += 2.0 * (1.0 - k / (lag + 1.0)) * gamma(k)
    if svar <= 0:
        return {"n": n, "mean": mean, "t": None, "reason": "non-positive long-run variance", "svar": svar}
    se = math.sqrt(svar / n)
    return {"n": n, "mean": mean, "se": se, "t": mean / se, "svar": svar}


def acf_adjusted_sharpe(returns: list[float]) -> dict:
    n = len(returns)
    if n < LAG + 2:
        return {"sharpe_365": None, "sharpe_acf": None, "reason": "too few observations"}
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if var <= 0:
        return {"sharpe_365": None, "sharpe_acf": None, "reason": "zero variance"}
    std = math.sqrt(var)
    sharpe_daily = mean / std
    sharpe_365 = sharpe_daily * math.sqrt(365.0)
    demeaned = [r - mean for r in returns]
    den = sum(x * x for x in demeaned)
    rhos = []
    for k in range(1, LAG + 1):
        num = sum(demeaned[t] * demeaned[t - k] for t in range(k, n))
        rhos.append(num / den if den else 0.0)
    factor = 1.0 + 2.0 * sum(rhos)
    sharpe_acf = sharpe_daily * math.sqrt(365.0 / factor) if factor > 0 else None
    return {
        "sharpe_365": sharpe_365,
        "sharpe_acf": sharpe_acf,
        "acf_factor": factor,
        "mean_daily": mean,
        "std_daily": std,
    }


def simulate(days, by_date, fundings, marks4, signal, sigma, eligible, mode: str):
    """mode: 'strategy' (vol target, halt, compound) or 'unit' (notional 1, no halt)."""
    vol_target = mode == "strategy"
    use_halt = mode == "strategy"
    compound = mode == "strategy"
    cash = EQUITY0 if compound else 0.0
    peak = EQUITY0 if compound else 1.0
    position = None
    pending = None
    halt = False
    halt_date = None
    fi = 0
    intrabar_breach_days = 0
    intrabar_examples = []
    trades = []
    equity_rows = []
    daily_pnl = []
    daily_ret = []
    price_pnl = 0.0
    funding_pnl = 0.0
    fees = 0.0
    fallback_marks = 0
    skipped_uncovered = 0
    max_dd = 0.0
    fund_set = {ft for ft, _ in fundings}
    step_ms = 8 * 3_600_000

    def hold_covered(signal_date) -> bool:
        entry_d = signal_date + timedelta(days=1)
        exit_d = signal_date + timedelta(days=21)
        if entry_d not in by_date or exit_d not in by_date:
            return False
        t0 = days[by_date[entry_d]]["close_time"]
        t1 = days[by_date[exit_d]]["close_time"]
        t = (t0 // step_ms + 1) * step_ms
        while t < t1:
            if t not in fund_set:
                return False
            t += step_ms
        return t != (t0 // step_ms + 1) * step_ms
    max_dd_date = None
    start_i = next(i for i, ok in enumerate(eligible) if ok)
    prev_equity = EQUITY0 if compound else 0.0

    def wealth_of(mark_px: float) -> float:
        if position is None:
            base = cash
        else:
            base = cash + position["side"] * position["qty"] * (mark_px - position["entry"])
        return base

    def apply_until(limit: int, inclusive: bool, pos):
        nonlocal fi, cash, funding_pnl, fallback_marks
        while fi < len(fundings):
            ft, rate = fundings[fi]
            if ft > limit or (ft == limit and not inclusive):
                break
            if pos is not None and ft > pos["entry_fill_time"]:
                m = mark_asof(marks4, ft)
                if m is None:
                    m = pos["entry"]
                    fallback_marks += 1
                delta = -pos["side"] * pos["qty"] * m * rate
                cash += delta
                funding_pnl += delta
                pos["funding"] += delta
            fi += 1

    for i, day in enumerate(days):
        if i < start_i:
            continue
        wealth_before = prev_equity
        exited_this_bar = False
        cash_open = cash
        peak_open = peak
        pos_open = position

        if pending and pending["kind"] == "exit" and position is not None:
            apply_until(day["close_time"], False, position)
            exit_px = day["px"]
            pnl = position["side"] * position["qty"] * (exit_px - position["entry"])
            fee = position["qty"] * exit_px * TAKER
            cash += pnl - fee
            price_pnl += pnl
            fees += fee
            trades.append(
                {
                    "side": position["side"],
                    "signal_date": position["signal_date"].isoformat(),
                    "entry_date": position["entry_date"].isoformat(),
                    "exit_date": day["date"].isoformat(),
                    "hold_days": (day["date"] - position["entry_date"]).days,
                    "entry": position["entry"],
                    "exit": exit_px,
                    "notional": position["notional"],
                    "price_pnl": pnl,
                    "funding": position["funding"],
                    "fees": position["fee_in"] + fee,
                    "net": pnl + position["funding"] - position["fee_in"] - fee,
                    "reason": pending["reason"],
                }
            )
            position = None
            pending = None
            exited_this_bar = True
        elif pending and pending["kind"] == "enter" and position is None and not halt:
            apply_until(day["close_time"], True, None)
            fill = day["px"]
            notional = pending["notional"]
            qty = notional / fill
            fee = notional * TAKER
            cash -= fee
            fees += fee
            position = {
                "side": pending["side"],
                "qty": qty,
                "entry": fill,
                "notional": notional,
                "signal_date": pending["signal_date"],
                "entry_date": day["date"],
                "entry_fill_time": day["close_time"],
                "funding": 0.0,
                "fee_in": fee,
            }
            pending = None
        elif position is not None:
            apply_until(day["close_time"], True, position)
        else:
            apply_until(day["close_time"], True, None)

        mark_px = day["mc"]
        equity = wealth_of(mark_px)
        if compound:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak else 0.0
            if dd > max_dd:
                max_dd = dd
                max_dd_date = day["date"].isoformat()
        else:
            dd = 0.0

        if (
            use_halt
            and pos_open is not None
            and pos_open["entry_date"] < day["date"]
        ):
            # Proxy only: start-of-day cash and peak against this day's mark range.
            m_star = pos_open["entry"] + (peak_open * (1.0 - HALT_DD) - cash_open) / (
                pos_open["side"] * pos_open["qty"]
            )
            adverse = day["ml"] if pos_open["side"] > 0 else day["mh"]
            breached = adverse <= m_star if pos_open["side"] > 0 else adverse >= m_star
            close_breach = dd >= HALT_DD
            if breached and not close_breach:
                intrabar_breach_days += 1
                if len(intrabar_examples) < 8:
                    intrabar_examples.append(
                        {
                            "date": day["date"].isoformat(),
                            "side": pos_open["side"],
                            "threshold_mark": m_star,
                            "mark_open": day["mo"],
                            "mark_extreme": adverse,
                            "close_dd": dd,
                        }
                    )

        halted_now = False
        if use_halt and position is not None and dd >= HALT_DD:
            exit_px = day["px"]
            pnl = position["side"] * position["qty"] * (exit_px - position["entry"])
            fee = exit_px * position["qty"] * TAKER
            cash += pnl - fee
            price_pnl += pnl
            fees += fee
            trades.append(
                {
                    "side": position["side"],
                    "signal_date": position["signal_date"].isoformat(),
                    "entry_date": position["entry_date"].isoformat(),
                    "exit_date": day["date"].isoformat(),
                    "hold_days": (day["date"] - position["entry_date"]).days,
                    "entry": position["entry"],
                    "exit": exit_px,
                    "notional": position["notional"],
                    "price_pnl": pnl,
                    "funding": position["funding"],
                    "fees": position["fee_in"] + fee,
                    "net": pnl + position["funding"] - position["fee_in"] - fee,
                    "reason": "halt",
                }
            )
            position = None
            pending = None
            halt = True
            halt_date = day["date"].isoformat()
            halted_now = True
            equity = cash
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak else 0.0
            if dd > max_dd:
                max_dd = dd
                max_dd_date = day["date"].isoformat()

        if not halt and not halted_now:
            if position is not None and pending is None:
                age = (day["date"] - position["signal_date"]).days
                s = signal[i]
                if age >= 20:
                    pending = {"kind": "exit", "reason": "time"}
                elif age >= 5 and s == -position["side"] and s != 0:
                    pending = {"kind": "exit", "reason": "flip"}
            elif (
                position is None
                and pending is None
                and not exited_this_bar
                and signal[i] != 0
                and sigma[i] is not None
                and hold_covered(day["date"])
            ):
                if vol_target:
                    scale = L_MAX if sigma[i] == 0 else min(L_MAX, TARGET_VOL / sigma[i])
                    equity_now = cash
                    notional = scale * equity_now
                    if notional * (1.0 + TAKER) > equity_now:
                        notional = equity_now / (1.0 + TAKER)
                else:
                    notional = 1.0
                if notional > 0:
                    pending = {
                        "kind": "enter",
                        "side": signal[i],
                        "notional": notional,
                        "signal_date": day["date"],
                    }
            elif (
                position is None
                and pending is None
                and not exited_this_bar
                and signal[i] != 0
                and sigma[i] is not None
                and not hold_covered(day["date"])
            ):
                skipped_uncovered += 1

        equity = cash if position is None else wealth_of(day["mc"])
        if compound and equity > peak:
            peak = equity
        row_pnl = (equity - wealth_before) if not compound else None
        if not compound:
            daily_pnl.append(equity - wealth_before)
        else:
            if wealth_before > 0:
                daily_ret.append(equity / wealth_before - 1.0)
        prev_equity = equity
        equity_rows.append(
            {
                "date": day["date"].isoformat(),
                "equity": equity,
                "dd": ((peak - equity) / peak if peak and compound else 0.0),
                "position": 0 if position is None else position["side"],
            }
        )

    end_equity = equity_rows[-1]["equity"] if equity_rows else cash
    open_trade = None
    if position is not None:
        last = days[-1]
        unr = position["side"] * position["qty"] * (last["mc"] - position["entry"])
        open_trade = {
            "side": position["side"],
            "signal_date": position["signal_date"].isoformat(),
            "entry_date": position["entry_date"].isoformat(),
            "entry": position["entry"],
            "unrealized_mark": unr,
            "funding": position["funding"],
        }
    return {
        "trades": trades,
        "equity_rows": equity_rows,
        "daily_pnl": daily_pnl,
        "daily_ret": daily_ret,
        "end_equity": end_equity,
        "halt": halt,
        "halt_date": halt_date,
        "max_dd": max_dd,
        "max_dd_date": max_dd_date,
        "price_pnl": price_pnl,
        "funding_pnl": funding_pnl,
        "fees": fees,
        "fallback_marks": fallback_marks,
        "skipped_uncovered": skipped_uncovered,
        "intrabar_breach_days": intrabar_breach_days,
        "intrabar_examples": intrabar_examples,
        "open_trade": open_trade,
        "start_date": days[start_i]["date"].isoformat(),
        "end_date": days[-1]["date"].isoformat(),
    }


def offset_test(days, by_date, fundings, marks4, signal) -> dict:
    """Fixed 20-day holds, unit notional, one grid per offset. No early exit, no halt."""
    signs = []
    detail = []
    n = len(days)
    fund_set = {ft for ft, _ in fundings}
    step_ms = 8 * 3_600_000

    def covered(signal_date) -> bool:
        entry_d = signal_date + timedelta(days=1)
        exit_d = signal_date + timedelta(days=21)
        if entry_d not in by_date or exit_d not in by_date:
            return False
        t0 = days[by_date[entry_d]]["close_time"]
        t1 = days[by_date[exit_d]]["close_time"]
        t = (t0 // step_ms + 1) * step_ms
        while t < t1:
            if t not in fund_set:
                return False
            t += step_ms
        return True

    for offset in range(20):
        rets = []
        i = offset
        while i < n:
            d = days[i]["date"]
            if signal[i] == 0 or not covered(d):
                i += 20
                continue
            entry_d = d + timedelta(days=1)
            exit_d = d + timedelta(days=21)
            if entry_d not in by_date or exit_d not in by_date:
                i += 20
                continue
            gap = False
            cursor = entry_d
            while cursor <= exit_d:
                if cursor not in by_date:
                    gap = True
                    break
                cursor += timedelta(days=1)
            if gap:
                i += 20
                continue
            ei = by_date[entry_d]
            xi = by_date[exit_d]
            entry = days[ei]["px"]
            exit_px = days[xi]["px"]
            side = signal[i]
            qty = 1.0 / entry
            fee = TAKER + qty * exit_px * TAKER
            funding = 0.0
            t0 = days[ei]["close_time"]
            t1 = days[xi]["close_time"]
            for ft, rate in fundings:
                if ft <= t0:
                    continue
                if ft >= t1:
                    break
                m = mark_asof(marks4, ft)
                if m is None:
                    m = entry
                funding += -side * qty * m * rate
            pnl = side * qty * (exit_px - entry) - fee + funding
            rets.append(pnl)
            i += 20
        if rets:
            mean = sum(rets) / len(rets)
            sgn = 0 if mean == 0 else (1 if mean > 0 else -1)
        else:
            mean = None
            sgn = None
        signs.append(sgn)
        detail.append({"offset": offset, "n": len(rets), "mean": mean, "sign": sgn})
    usable = [s for s in signs if s in (-1, 1)]
    stable = len(usable) == 20 and len(set(usable)) == 1
    return {"stable_sign": stable, "offsets": detail}


def max_dd_of(equity: list[float]) -> float:
    peak = equity[0]
    worst = 0.0
    for e in equity:
        if e > peak:
            peak = e
        if peak:
            worst = max(worst, (peak - e) / peak)
    return worst


def main():
    daily_rows, mark_rows, fund_rows, m4_rows = load_or_download()
    days, by_date, fundings, marks4, gaps, miss_mark, miss_trade = build_panels(
        daily_rows, mark_rows, fund_rows, m4_rows
    )
    signal, sigma, eligible = prepare_signals(days, by_date)
    strategy = simulate(days, by_date, fundings, marks4, signal, sigma, eligible, "strategy")
    unit = simulate(days, by_date, fundings, marks4, signal, sigma, eligible, "unit")
    offsets = offset_test(days, by_date, fundings, marks4, signal)

    eq = [r["equity"] for r in strategy["equity_rows"]]
    rets = strategy["daily_ret"]
    sharpe = acf_adjusted_sharpe(rets)
    unit_t = newey_west_t(unit["daily_pnl"], LAG)
    strat_t = newey_west_t(rets, LAG)
    completed = strategy["trades"]
    span_days = (days[-1]["date"] - days[0]["date"]).days
    elig_days = (datetime.fromisoformat(strategy["end_date"]).date() - datetime.fromisoformat(strategy["start_date"]).date()).days
    total_return = strategy["end_equity"] / EQUITY0 - 1.0
    cagr = (strategy["end_equity"] / EQUITY0) ** (365.0 / elig_days) - 1.0 if elig_days > 0 and strategy["end_equity"] > 0 else None

    summary = {
        "instrument": INST,
        "venue": "OKX",
        "label": "one-bar delayed, spread missing, constant Lv1 taker 0.0005",
        "equity0": EQUITY0,
        "bars": {
            "n": len(days),
            "first": days[0]["date"].isoformat(),
            "last": days[-1]["date"].isoformat(),
            "first_close": days[0]["px"],
            "last_close": days[-1]["px"],
            "calendar_gaps": gaps,
            "trade_days_missing_mark": miss_mark,
            "mark_days_missing_trade": miss_trade,
            "span_days": span_days,
        },
        "funding_prints": {
            "n": len(fundings),
            "first": datetime.fromtimestamp(fundings[0][0] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "last": datetime.fromtimestamp(fundings[-1][0] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "missing_8h_slots": (lambda a, b, s: sum(
                1 for t in range(a, b + 1, 8 * 3_600_000) if t not in s
            ))(fundings[0][0], fundings[-1][0], {ft for ft, _ in fundings}),
            "source": "OKX monthly swaprates archive from 2022-03 plus the public REST history for the newest settlements",
        },
        "mark_4h": len(marks4),
        "strategy": {
            "start": strategy["start_date"],
            "end": strategy["end_date"],
            "end_equity": strategy["end_equity"],
            "total_return": total_return,
            "cagr": cagr,
            "max_dd": strategy["max_dd"],
            "max_dd_date": strategy["max_dd_date"],
            "max_dd_on_saved_equity": max_dd_of(eq),
            "halt": strategy["halt"],
            "halt_date": strategy["halt_date"],
            "completed_round_trips": len(completed),
            "hold_days": {
                "min": min((t["hold_days"] for t in completed), default=None),
                "max": max((t["hold_days"] for t in completed), default=None),
                "reasons": {
                    k: sum(1 for t in completed if t["reason"] == k) for k in ("time", "flip", "halt")
                },
            },
            "price_pnl": strategy["price_pnl"],
            "funding_pnl": strategy["funding_pnl"],
            "fees": strategy["fees"],
            "funding_mark_fallbacks": strategy["fallback_marks"],
            "entries_skipped_missing_funding": strategy["skipped_uncovered"],
            "intrabar_breach_days_close_path_missed": strategy["intrabar_breach_days"],
            "intrabar_examples": strategy["intrabar_examples"],
            "open_trade": strategy["open_trade"],
            "sharpe": sharpe,
            "hac_t_daily_returns": strat_t,
            "net_wins": sum(1 for t in completed if t["net"] > 0),
        },
        "unit_notional_no_halt": {
            "note": "Fixed entry notional of 1, same 5-to-20-day rules, no volatility scaling, no 15% halt. HAC lag 20 on daily pnl.",
            "hac": unit_t,
            "funding_pnl": unit["funding_pnl"],
            "fees": unit["fees"],
            "price_pnl": unit["price_pnl"],
            "completed_round_trips": len(unit["trades"]),
            "end_pnl": unit["end_equity"],
        },
        "offset_grid": {
            "stable_sign": offsets["stable_sign"],
            "offsets": offsets["offsets"],
        },
        "walk_forward_gate": {
            "required_completed_round_trips": 190,
            "strategy_completed_round_trips": len(completed),
            "met": len(completed) >= 190,
        },
    }
    out = ROOT / "backtest_summary.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (ROOT / "backtest_equity.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "equity", "dd", "position"])
        w.writeheader()
        w.writerows(strategy["equity_rows"])
    with (ROOT / "backtest_trades.csv").open("w", newline="", encoding="utf-8") as f:
        fields = [
            "side",
            "signal_date",
            "entry_date",
            "exit_date",
            "hold_days",
            "entry",
            "exit",
            "notional",
            "price_pnl",
            "funding",
            "fees",
            "net",
            "reason",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(completed)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
