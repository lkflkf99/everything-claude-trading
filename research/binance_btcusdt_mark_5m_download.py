"""Download BTCUSDT USDT-M perpetual MARK PRICE 5m klines from Binance archive.

Source: https://data.binance.vision/data/futures/um/{monthly,daily}/markPriceKlines/BTCUSDT/5m/
Output: research/data/binance_um_btcusdt_perp_mark_5m.csv

Used for liquidation checks alongside the trade-price backtest.
Same pipeline as the trade-price pull: sha256 verification, us->ms
normalization, dedup, gap detection. Volume fields are zero by design
on mark-price klines.
"""

from __future__ import annotations

import csv
import hashlib
import io
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
BASE = "https://data.binance.vision/data/futures/um"
DATA_DIR = Path(__file__).resolve().parent / "data"
OUT = DATA_DIR / "binance_um_btcusdt_perp_mark_5m.csv"

FIRST_MONTH = (2019, 9)
BAR_MS = 5 * 60 * 1000


def fetch(url: str, tries: int = 5) -> bytes | None:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research-data-pull"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last = exc
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(0.8 * (i + 1))
    raise RuntimeError(f"failed {url}: {last}")


def norm_ms(v: str) -> int:
    x = int(v)
    return x // 1000 if x > 10**14 else x


def parse_zip(blob: bytes) -> list[list[str]]:
    rows = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        text = zf.read(zf.namelist()[0]).decode("utf-8")
    for rec in csv.reader(io.StringIO(text)):
        if not rec or rec[0].strip().lower() == "open_time":
            continue
        rec[0] = str(norm_ms(rec[0]))
        rec[6] = str(norm_ms(rec[6]))
        rows.append(rec)
    return rows


def verify_checksum(url: str, blob: bytes) -> str:
    cs = fetch(url + ".CHECKSUM")
    if cs is None:
        return "no-checksum-file"
    expected = cs.decode("utf-8").split()[0].strip()
    actual = hashlib.sha256(blob).hexdigest()
    return "ok" if actual == expected else f"MISMATCH exp={expected} got={actual}"


def month_iter(a, b):
    y, m = a
    while (y, m) <= b:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def day_iter(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today_utc = datetime.now(timezone.utc).date()
    yesterday = today_utc - timedelta(days=1)
    last_full_month = (today_utc.year, today_utc.month - 1) if today_utc.month > 1 else (today_utc.year - 1, 12)

    bars: dict[int, list[str]] = {}
    checksum_bad = []
    fallback_days: list[date] = []

    for y, m in month_iter(FIRST_MONTH, last_full_month):
        url = f"{BASE}/monthly/markPriceKlines/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{y}-{m:02d}.zip"
        blob = fetch(url)
        if blob is None:
            if date(y, m, 1) <= yesterday:
                print(f"  monthly {y}-{m:02d} 404, will try daily files", flush=True)
                fallback_days.extend(day_iter(date(y, m, 1), min(date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1), yesterday)))
            continue
        status = verify_checksum(url, blob)
        if status not in ("ok", "no-checksum-file"):
            checksum_bad.append((f"{y}-{m:02d}", status))
        rows = parse_zip(blob)
        for rec in rows:
            bars[int(rec[0])] = rec
        print(f"  monthly {y}-{m:02d} rows={len(rows)} total={len(bars)} sha256={status}", flush=True)
        time.sleep(0.05)

    first_of_month = date(today_utc.year, today_utc.month, 1)
    for d in sorted(set(fallback_days) | set(day_iter(first_of_month, yesterday))):
        url = f"{BASE}/daily/markPriceKlines/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{d.isoformat()}.zip"
        blob = fetch(url)
        if blob is None:
            print(f"  daily {d} 404, skip", flush=True)
            continue
        status = verify_checksum(url, blob)
        if status not in ("ok", "no-checksum-file"):
            checksum_bad.append((d.isoformat(), status))
        rows = parse_zip(blob)
        for rec in rows:
            bars[int(rec[0])] = rec
        print(f"  daily {d} rows={len(rows)} total={len(bars)} sha256={status}", flush=True)
        time.sleep(0.05)

    if not bars:
        sys.exit("no data downloaded")

    ts_sorted = sorted(bars)
    gaps = [(a, b, (b - a) // BAR_MS - 1) for a, b in zip(ts_sorted, ts_sorted[1:]) if b - a != BAR_MS]
    if gaps:
        print(f"GAPS: {len(gaps)} discontinuities", flush=True)
        for a, b, missing in gaps[:20]:
            fmt = "%Y-%m-%d %H:%M UTC"
            print(f"  {datetime.fromtimestamp(a/1000, timezone.utc):{fmt}} -> {datetime.fromtimestamp(b/1000, timezone.utc):{fmt}} missing~{missing} bars", flush=True)
    else:
        print("GAPS: none, series is continuous", flush=True)

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["open_time_ms", "open_time_utc", "open", "high", "low", "close"])
        for t in ts_sorted:
            r = bars[t]
            iso = datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            w.writerow([t, iso, r[1], r[2], r[3], r[4]])

    first = datetime.fromtimestamp(ts_sorted[0] / 1000, timezone.utc)
    last = datetime.fromtimestamp(ts_sorted[-1] / 1000, timezone.utc)
    print(f"WROTE {OUT} rows={len(ts_sorted)}", flush=True)
    print(f"COVERAGE {first:%Y-%m-%d %H:%M UTC} -> {last:%Y-%m-%d %H:%M UTC}", flush=True)
    print(f"CHECKSUM_MISMATCHES {len(checksum_bad)} {checksum_bad[:5]}", flush=True)


if __name__ == "__main__":
    main()
