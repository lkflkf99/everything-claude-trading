"""Download full BTCUSDT USDT-M perpetual funding-rate history from Binance fapi.

Source: GET https://fapi.binance.com/fapi/v1/fundingRate (public, official exchange API)
Output: research/data/binance_um_btcusdt_perp_funding.csv
"""

from __future__ import annotations

import csv
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "binance_um_btcusdt_perp_funding.csv"
START_MS = 1567296000000  # 2019-09-01 UTC, before perp launch


def get(url: str, tries: int = 6):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research-data-pull"})
            with urllib.request.urlopen(req, timeout=40) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.8 * (i + 1))
    raise RuntimeError(f"failed {url}: {last}")


def main() -> None:
    rows: dict[int, dict] = {}
    start = START_MS
    while True:
        url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime={start}&limit=1000"
        batch = get(url)
        if not batch:
            break
        for r in batch:
            rows[int(r["fundingTime"])] = r
        last_t = int(batch[-1]["fundingTime"])
        print(f"  fetched up to {datetime.fromtimestamp(last_t/1000, timezone.utc):%Y-%m-%d %H:%M} total={len(rows)}", flush=True)
        if len(batch) < 1000:
            break
        start = last_t + 1
        time.sleep(0.15)

    ts = sorted(rows)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["funding_time_ms", "funding_time_utc", "funding_rate", "mark_price"])
        for t in ts:
            r = rows[t]
            iso = datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            w.writerow([t, iso, r["fundingRate"], r.get("markPrice", "")])

    # verify 8h spacing and slot alignment (00/08/16 UTC)
    odd = [t for t in ts if t % (8 * 3_600_000) != 0]
    gaps = [(a, b) for a, b in zip(ts, ts[1:]) if b - a != 8 * 3_600_000]
    print(f"WROTE {OUT} rows={len(ts)}", flush=True)
    print(f"first={datetime.fromtimestamp(ts[0]/1000, timezone.utc):%Y-%m-%d %H:%M UTC} last={datetime.fromtimestamp(ts[-1]/1000, timezone.utc):%Y-%m-%d %H:%M UTC}", flush=True)
    print(f"off_8h_grid={len(odd)} spacing_anomalies={len(gaps)}", flush=True)
    for a, b in gaps[:10]:
        print(f"  gap {datetime.fromtimestamp(a/1000, timezone.utc):%Y-%m-%d %H:%M} -> {datetime.fromtimestamp(b/1000, timezone.utc):%Y-%m-%d %H:%M}", flush=True)


if __name__ == "__main__":
    main()
