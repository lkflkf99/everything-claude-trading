#!/usr/bin/env python3
"""BTCUSDT funding-carry PAPER bot — faithful SPEC v1.1 implementation.

Paper-trades the approved delta-neutral funding-carry strategy (long spot +
short perp, 1:1 notional, 2x isolated short, theta=20% rebalance, floor-locked
carry sweep). Imports the exact pure mechanics from the validated backtest
engine (research/carry/carry_backtest.py) so paper logic cannot drift from
the tested spec. NO LIVE ORDERS: this bot never touches authenticated
endpoints; "fills" are simulated at observed prices with taker fees.

Modes:
  live    poll Binance public REST; process funding stamps, completed 4h bars,
          monitors with paper actions (kill switch / de-risk ladder / floors)
  replay  drive the bot with the historical CSVs in pure-mechanics mode
          (monitors alert-only, like the backtest) and verify it reproduces
          carry_bt_results.json['base_t20_close_high'] exactly

Usage:
  # replay verification (full 2019-12-31 -> 2026-10-31 parity check)
  python3 research/carry/bot/carry_paper_bot.py --mode replay --verify

  # live paper operation (public data only; poll every 300s)
  python3 research/carry/bot/carry_paper_bot.py --mode live --capital 10000 \
      --enter --interval-sec 300

  # one-shot monitor poll on an existing paper position
  python3 research/carry/bot/carry_paper_bot.py --mode live --once

State: <state-dir>/state.json (position ledger), events.log (JSONL audit),
alerts.log (WARN/CRITICAL/ACTION), dashboard.txt (latest monitor snapshot).

Paper approximations (documented, bounded):
  - Live funding cashflow uses the mark price at poll time, not exactly at the
    stamp; error << 1bp of notional per stamp in normal conditions.
  - Missed stamps while offline are backfilled from /fapi/v1/fundingRate
    (limit=8, ~64h); longer outages need --mode replay-style repair.
  - ADL: true detection needs an authenticated feed (/fapi/v1/adlQuantile,
    user-data forceOrders). Paper mode runs a stress heuristic (4h bar drop
    <= -10% or mark/perp dislocation > 0.5%) that emits the ADL playbook.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent
CARRY_DIR = BOT_DIR.parent
RESEARCH_DIR = CARRY_DIR.parent
sys.path.insert(0, str(CARRY_DIR))

from carry_backtest import (  # noqa: E402  (validated spec mechanics)
    STEP, TAKER_PERP, TAKER_SPOT, THETA_BASE,
    floor_step, funding_cashflow, liq_price_short, rebalance_math,
    sweep_carry_math,
)

H4_MS = 4 * 3_600_000
DAY_MS = 86_400_000
UTC = timezone.utc
NAN = float("nan")

# spec constants (SPEC_v1.1 §3, §9, §10)
ECON_FLOOR_ANN = 0.015          # economic floor: 90d net carry < 1.5%/yr
BREAKER_ANN = 0.0               # circuit breaker: 90d net carry < 0%/yr
FLOOR_WINDOW_D = 90
FLOOR_PERSIST_D = 60
KILL_DIST = 0.05                # kill switch: liq distance < 5% -> cut 50%
WARN_DIST = 0.10                # alert: liq distance < 10%
PREALERT_TRIG = 0.18            # anchor proximity pre-alert at +18%
RESERVE_CAP_MULT = 0.2          # on-exchange reserve cap = 0.2 * N
DERISK_DD_1, DERISK_DD_2 = 0.05, 0.08   # equity-DD ladder: halve / wind down
ADL_BAR_DROP = -0.10            # stress heuristic: 4h bar return <= -10%
ADL_DISLOC = 0.005              # or |mark-perp|/perp > 0.5%


def ts_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")


def _num(v: str):
    try:
        return int(v)
    except (ValueError, TypeError):
        try:
            return float(v)
        except (ValueError, TypeError):
            return v  # keep non-numeric strings (e.g. *_utc columns)


# ---------------------------------------------------------------- feeds ----
class BinancePublicFeed:
    """Read-only public REST. No authentication, no orders."""

    SPOT_HOSTS = ("https://data-api.binance.vision",   # geo-neutral data mirror
                  "https://api.binance.com", "https://api1.binance.com")
    FAPI_HOST = "https://fapi.binance.com"

    def __init__(self, tries: int = 4, timeout: int = 15):
        self.tries, self.timeout = tries, timeout

    def _get(self, url: str):
        last = None
        for i in range(self.tries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "carry-paper-bot/1.0"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(0.6 * (i + 1))
        raise RuntimeError(f"feed failed {url}: {last}")

    def premium_index(self) -> dict:
        return self._get(f"{self.FAPI_HOST}/fapi/v1/premiumIndex?symbol=BTCUSDT")

    def klines(self, market: str, interval: str, limit: int = 2) -> list:
        path = "api/v3" if market == "spot" else "fapi/v1"
        hosts = self.SPOT_HOSTS if market == "spot" else (self.FAPI_HOST,)
        last = None
        for host in hosts:
            try:
                return self._get(f"{host}/{path}/klines?symbol=BTCUSDT"
                                 f"&interval={interval}&limit={limit}")
            except RuntimeError as exc:
                last = exc
        raise last

    def funding_rate(self, limit: int = 8) -> list:
        return self._get(f"{self.FAPI_HOST}/fapi/v1/fundingRate?symbol=BTCUSDT&limit={limit}")


class ReplayFeed:
    """Historical CSVs (perp 4h, spot 4h, funding), aligned like the backtest."""

    def __init__(self):
        self.p4 = self._rows(RESEARCH_DIR / "data" / "binance_um_btcusdt_perp_4h.csv")
        self.s4 = {r["open_time_ms"]: r
                   for r in self._rows(CARRY_DIR / "data" / "binance_spot_btcusdt_4h.csv")}
        fun = self._rows(RESEARCH_DIR / "data" / "binance_um_btcusdt_perp_funding.csv")
        dedup = {}
        for r in fun:  # floor ms jitter to the hour, dedup (spec §6)
            ts = (r["funding_time_ms"] // 3_600_000) * 3_600_000
            dedup.setdefault(ts, {"ts": ts, "rate": r["funding_rate"],
                                  "mark": r.get("mark_price")})
        self.funding = [dedup[k] for k in sorted(dedup)]

    @staticmethod
    def _rows(path: Path) -> list[dict]:
        with path.open() as f:
            return [{k: _num(v) for k, v in rec.items()} for rec in csv.DictReader(f)]


# ---------------------------------------------------------------- state ----
@dataclass
class State:
    capital: float = 0.0
    notional: float = 0.0
    Q: float = 0.0
    EP: float = 0.0          # perp entry price (fixed for position life)
    M: float = 0.0           # isolated wallet (margin + realized flows)
    M_floor: float = 0.0     # v1.1 sweep floor, re-anchored at entry/rebalance/kill
    R: float = 0.0           # reserve (0.1N + swept carry)
    P0: float = 0.0          # rebalance anchor
    entry_ts: int = 0
    open: bool = False
    halted: bool = False
    peak_equity: float = 0.0
    funding_credits: list = field(default_factory=list)   # [[ts, amount], ...]
    applied_funding: list = field(default_factory=list)   # stamp ts ints
    rebalances: list = field(default_factory=list)
    sweeps_total: float = 0.0
    funding_total: float = 0.0
    skipped_nan: int = 0
    floor_below_since: dict = field(default_factory=dict)  # {"econ": ms|None, "brk": ms|None}
    kill_cooldown_until: int = 0


class Store:
    def __init__(self, d: Path):
        d.mkdir(parents=True, exist_ok=True)
        self.dir, self.state_p = d, d / "state.json"
        self.events_p = d / "events.log"
        self.alerts_p = d / "alerts.log"
        self.dash_p = d / "dashboard.txt"

    def load(self) -> State:
        if self.state_p.exists():
            return State(**json.loads(self.state_p.read_text()))
        return State()

    def save(self, st: State):
        self.state_p.write_text(json.dumps(st.__dict__, indent=1))

    def event(self, kind: str, **kw):
        with self.events_p.open("a") as f:
            f.write(json.dumps({"kind": kind, **kw}) + "\n")

    def alert(self, sev: str, msg: str, **kw):
        line = json.dumps({"sev": sev, "msg": msg, **kw})
        print(f"[{sev}] {msg}", flush=True)
        with self.alerts_p.open("a") as f:
            f.write(line + "\n")
        self.event("alert", sev=sev, msg=msg, **kw)


# ------------------------------------------------------------------ bot ----
class CarryPaperBot:
    """SPEC v1.1 state machine. pure=True disables paper risk ACTIONS
    (kill switch / de-risk / floor wind-down) so replay reproduces the
    pure-mechanics backtest; alerts still fire (deduplicated)."""

    def __init__(self, store: Store, theta: float = THETA_BASE, pure: bool = False):
        self.store, self.theta, self.pure = store, theta, pure
        self.st = store.load()
        self._alerted: set[str] = set()

    def _flag(self, key: str, active: bool, sev: str, msg: str, **kw):
        """Deduplicated alert on condition edges."""
        if active and key not in self._alerted:
            self._alerted.add(key)
            self.store.alert(sev, msg, **kw)
        elif not active and key in self._alerted:
            self._alerted.discard(key)
            self.store.alert("INFO", f"recovered: {key}")

    # ---- accounting ----
    def equity(self, px_spot: float, px_perp: float) -> float:
        s = self.st
        return s.Q * (px_spot - px_perp) + s.Q * s.EP + s.M + s.R

    def liq_distance(self, mark: float) -> float:
        s = self.st
        if s.Q <= 0:
            return float("inf")
        return liq_price_short(s.M, s.Q, s.EP) / mark - 1.0

    # ---- spec §5: entry ----
    def enter(self, ts: int, px_perp: float, px_spot: float, capital: float):
        s = self.st
        assert not s.open, "position already open"
        N = capital / 1.6
        Q = floor_step(N / px_perp)
        fee_s, fee_p = Q * px_spot * TAKER_SPOT, Q * px_perp * TAKER_PERP
        M = 0.5 * N
        R = capital - Q * px_spot - fee_s - M - fee_p
        s.__dict__.update(capital=capital, notional=N, Q=Q, EP=px_perp, M=M,
                          M_floor=M, R=R, P0=px_perp, entry_ts=ts, open=True,
                          halted=False, peak_equity=capital)
        self.store.event("entry", ts=ts_str(ts), Q=Q, EP=px_perp, px_spot=px_spot,
                         fee_s=round(fee_s, 2), fee_p=round(fee_p, 2),
                         M=round(M, 2), R=round(R, 2))
        self.store.alert("ACTION", f"ENTRY paper position: Q={Q} BTC @ perp {px_perp}, N=${N:,.0f}")
        self.store.save(s)

    # ---- spec §6: funding accrual ----
    def apply_funding(self, ts: int, rate: float, mark: float):
        s = self.st
        if not s.open or ts <= s.entry_ts or ts in s.applied_funding:
            return
        if not math.isfinite(mark):  # fallback: entry-price mark (bounded error)
            mark = s.EP
        cf = funding_cashflow(s.Q, mark, rate)
        s.M += cf
        s.applied_funding.append(ts)
        s.funding_credits.append([ts, cf])
        s.funding_total += cf
        self.store.event("funding", ts=ts_str(ts), rate=rate, mark=round(mark, 2),
                         cashflow=round(cf, 4), M=round(s.M, 2))

    # ---- spec §7: 4h bar processing (rebalance trigger or v1.1 sweep) ----
    def process_4h_bar(self, ts: int, high_p: float, close_p: float, close_s: float):
        s = self.st
        if not s.open or s.halted:
            return
        if high_p >= (1.0 + self.theta) * s.P0:
            if not (math.isfinite(close_p) and math.isfinite(close_s)):
                s.skipped_nan += 1
                self.store.event("rebalance_skipped_nan", ts=ts_str(ts))
                return
            rb = rebalance_math(s.Q, s.M, s.R, s.EP, close_s, close_p)
            if rb is None:
                self.store.alert("WARN", f"rebalance skipped: Q/6 below step @ {ts_str(ts)}")
                return
            s.Q, s.M, s.R = rb["Q"], rb["M"], rb["R"]
            s.P0 = close_p
            s.M_floor = s.M
            eff = ts + H4_MS                      # effective execution instant (bar close)
            s.rebalances.append([eff, rb["d"], close_p])
            self.store.event("rebalance", ts=ts_str(eff), bar_open=ts_str(ts), delta=rb["d"],
                             exec_perp=close_p, exec_spot=close_s, Q_after=s.Q,
                             X_to_margin=round(rb["X"], 2),
                             X_from_R=round(rb["X_from_R"], 2), unmet=round(rb["unmet"], 2))
            self.store.alert("ACTION", f"REBALANCE #{len(s.rebalances)}: -{rb['d']} BTC both legs "
                                       f"@ {close_p:,.0f} (eff {ts_str(eff)})")
            if rb["unmet"] > 1e-9:
                self.store.alert("CRITICAL", f"reserve top-up UNMET ${rb['unmet']:.2f} — "
                                             "margin below q=0.5")
        else:
            w = sweep_carry_math(s.M, s.M_floor)
            if w > 0:
                s.M -= w
                s.R += w
                s.sweeps_total += w
                self.store.event("sweep", ts=ts_str(ts + H4_MS), amount=round(w, 4),
                                 M=round(s.M, 2))

    # ---- spec §8: wind-down (perp first, then spot) ----
    def wind_down(self, ts: int, px_perp: float, px_spot: float, reason: str):
        s = self.st
        if not s.open:
            return
        fee_p = s.Q * px_perp * TAKER_PERP
        s.M += s.Q * (s.EP - px_perp) - fee_p
        s.R += s.M
        fee_s = s.Q * px_spot * TAKER_SPOT
        s.R += s.Q * px_spot - fee_s
        final = s.R
        self.store.event("wind_down", ts=ts_str(ts), reason=reason, final_equity=round(final, 2),
                         funding_total=round(s.funding_total, 2), rebalances=len(s.rebalances))
        self.store.alert("ACTION", f"WIND-DOWN ({reason}): final equity ${final:,.2f}")
        s.open, s.halted, s.Q, s.M = False, True, 0.0, 0.0
        s.R = final
        self.store.save(s)

    # ---- spec §9: kill switch / de-risk ladder ----
    def _deleverage(self, frac: float, ts: int, px_perp: float, px_spot: float, why: str):
        """Cut both legs by frac. Freed margin STAYS in the isolated wallet
        (raises LP = wider liquidation distance); spot proceeds go to reserve.
        Floor re-anchors to the new wallet so the sweep never drains the
        safety buffer."""
        s = self.st
        d = floor_step(s.Q * frac)
        if d < STEP:
            self.store.alert("WARN", f"deleverage noop: {frac:.0%} of Q below step")
            return
        fee_p = d * px_perp * TAKER_PERP
        s.M += d * (s.EP - px_perp) - fee_p      # realize short uPnL on closed part
        fee_s = d * px_spot * TAKER_SPOT
        s.R += d * px_spot - fee_s               # spot proceeds to reserve
        s.Q = round(s.Q - d, 10)
        s.M_floor = s.M                          # retain freed margin as buffer
        lp = liq_price_short(s.M, s.Q, s.EP)
        self.store.event("deleverage", ts=ts_str(ts), frac=frac, delta=d, reason=why,
                         Q_after=s.Q, M=round(s.M, 2), R=round(s.R, 2), LP_after=round(lp, 2))
        self.store.alert("CRITICAL", f"DELEVERAGE {frac:.0%} ({why}) @ {px_perp:,.0f}; "
                                     f"LP now {lp:,.0f}")

    # ---- spec §10: monitors (every poll; actions suppressed in pure mode) ----
    def update_monitors(self, ts: int, mark: float, px_spot: float, px_perp: float):
        s = self.st
        if not s.open or s.halted or not all(map(math.isfinite, (mark, px_spot, px_perp))):
            return {}
        dist = self.liq_distance(mark)
        E = self.equity(px_spot, px_perp)
        s.peak_equity = max(s.peak_equity, E)
        dd = E / s.peak_equity - 1.0

        kill = dist < KILL_DIST and ts >= s.kill_cooldown_until
        if kill and not self.pure:
            self._deleverage(0.5, ts, px_perp, px_spot,
                             f"kill switch: liq distance {dist:.1%} < 5%")
            s.kill_cooldown_until = ts + DAY_MS
        self._flag("liq_kill", kill, "CRITICAL",
                   f"kill switch {'FIRED' if not self.pure else 'would fire'}: liq distance "
                   f"{dist:.1%} < 5%")
        self._flag("liq_warn", KILL_DIST <= dist < WARN_DIST, "WARN",
                   f"liquidation distance {dist:.1%} < 10%")

        trig_dist = px_perp / s.P0 - 1.0
        self._flag("anchor", trig_dist >= PREALERT_TRIG, "WARN",
                   f"anchor proximity: +{trig_dist:.1%} of +20% trigger — rebalance imminent")

        if dd <= -DERISK_DD_2:
            self._flag("dd2", True, "CRITICAL",
                       f"de-risk ladder: drawdown {dd:.1%} beyond -8% → wind down")
            if not self.pure:
                self.wind_down(ts, px_perp, px_spot, "de-risk ladder -8%")
                return {}
        elif dd <= -DERISK_DD_1:
            fire = ts >= s.kill_cooldown_until
            self._flag("dd1", True, "CRITICAL",
                       f"de-risk ladder: drawdown {dd:.1%} beyond -5% → halve")
            if fire and not self.pure:
                self._deleverage(0.5, ts, px_perp, px_spot,
                                 f"de-risk ladder: drawdown {dd:.1%}")
                s.kill_cooldown_until = ts + DAY_MS
        else:
            self._flag("dd1", False, "", "")
            self._flag("dd2", False, "", "")

        # economic floor / circuit breaker: rolling 90d annualized net carry / notional
        cut = ts - FLOOR_WINDOW_D * DAY_MS
        c90 = sum(c for t, c in s.funding_credits if t > cut)
        rate = (c90 * 365.0 / FLOOR_WINDOW_D) / (s.Q * mark) if s.Q * mark > 0 else 0.0
        for key, thr in (("econ", ECON_FLOOR_ANN), ("brk", BREAKER_ANN)):
            since = s.floor_below_since.get(key)
            if rate < thr:
                if not since:
                    s.floor_below_since[key] = ts
                elif ts - since >= FLOOR_PERSIST_D * DAY_MS:
                    label = ("ECONOMIC FLOOR breached: 90d net carry %.2f%%/yr < 1.5%% for 60d"
                             " — wind down per spec" % (rate * 100)) if key == "econ" else \
                            ("CIRCUIT BREAKER: 90d carry %.2f%%/yr < 0 for 60d — review"
                             % (rate * 100))
                    self._flag(key, True, "CRITICAL" if key == "econ" else "WARN", label)
                    if key == "econ" and not self.pure:
                        self.wind_down(ts, px_perp, px_spot, "economic floor")
                        return {}
            else:
                s.floor_below_since[key] = None
                self._flag(key, False, "", "")

        self._flag("reserve_cap", s.R > RESERVE_CAP_MULT * s.notional, "INFO",
                   f"reserve ${s.R:,.0f} exceeds 0.2N cap — sweep off-venue (manual)")

        return {"ts": ts_str(ts), "mark": mark, "liq_dist": round(dist, 4),
                "equity": round(E, 2), "drawdown": round(dd, 4), "Q": s.Q,
                "M": round(s.M, 2), "M_floor": round(s.M_floor, 2), "R": round(s.R, 2),
                "anchor": s.P0, "trig_dist": round(trig_dist, 4),
                "carry_90d_ann": round(rate, 4), "funding_total": round(s.funding_total, 2),
                "rebalances": len(s.rebalances)}

    # ---- ADL stress heuristic (paper; live hooks in module docstring) ----
    def adl_watch(self, ts: int, bar_open: float, bar_close: float, mark: float, perp: float):
        if not self.st.open or not all(map(math.isfinite, (bar_open, bar_close, mark, perp))):
            return
        ret = bar_close / bar_open - 1.0
        disloc = abs(mark - perp) / perp if perp else 0.0
        self._flag("adl_stress", ret <= ADL_BAR_DROP or disloc > ADL_DISLOC, "ACTION",
                   f"ADL STRESS (4h {ret:.1%}, dislocation {disloc:.2%}) @ {ts_str(ts)} — "
                   "PLAYBOOK: 1) verify short leg intact 2) if ADL'd, re-hedge spot within 1h "
                   "3) resume monitors. Live: wire /fapi/v1/adlQuantile + forceOrders stream.")


# ------------------------------------------------------------ live loop ----
def live_loop(args):
    store = Store(Path(args.state_dir))
    bot = CarryPaperBot(store, theta=args.theta, pure=False)
    feed = BinancePublicFeed()
    processed_bars: set[int] = set()

    def poll():
        now = int(time.time() * 1000)
        pi = feed.premium_index()
        mark = float(pi["markPrice"])
        # funding: backfill settled stamps (covers ~64h downtime)
        for fr in feed.funding_rate(limit=8):
            fts = (int(fr["fundingTime"]) // 3_600_000) * 3_600_000
            bot.apply_funding(fts, float(fr["fundingRate"]), mark)
        # completed 4h bars: last kline may be forming; completed = close time <= now
        p4 = feed.klines("futures", "4h", 2)
        s4 = feed.klines("spot", "4h", 2)
        s4_map = {int(b[0]): b for b in s4}
        for pb in p4:
            bt = int(pb[0])
            if bt + H4_MS > now or bt in processed_bars or bt <= bot.st.entry_ts:
                continue
            processed_bars.add(bt)
            sb = s4_map.get(bt)
            close_s = float(sb[4]) if sb else NAN
            bot.process_4h_bar(bt, float(pb[2]), float(pb[4]), close_s)
            bot.adl_watch(bt, float(pb[1]), float(pb[4]), mark, float(pb[4]))
        px_perp = float(p4[-1][4])
        px_spot = float(s4[-1][4])
        dash = bot.update_monitors(now, mark, px_spot, px_perp)
        if dash:
            store.dash_p.write_text(json.dumps(dash, indent=1))
        store.save(bot.st)

    if args.enter:
        pi = feed.premium_index()
        s4 = feed.klines("spot", "4h", 1)
        bot.enter(int(time.time() * 1000), float(pi["markPrice"]), float(s4[-1][4]), args.capital)
    while True:
        try:
            poll()
        except Exception as exc:  # noqa: BLE001
            store.alert("WARN", f"poll failed (feed/network): {exc}")
        if args.once:
            break
        time.sleep(args.interval_sec)


# --------------------------------------------------------------- replay ----
def replay(args):
    """Reproduce the backtest event order exactly: for each 4h bar (open t),
    apply the funding stamp at the bar-close instant t+4h FIRST (charges old
    size), then the trigger check / sweep at close. Funding stamps are floored
    to the hour and windowed to (t0, t_end] like carry_backtest.build_funding.
    Spot-missing bars: trigger check skipped (counted), sweep unaffected.
    """
    store = Store(Path(args.state_dir))
    bot = CarryPaperBot(store, theta=args.theta, pure=True)
    feed = ReplayFeed()

    t0 = feed.p4[0]["open_time_ms"]
    t_end = feed.p4[-1]["open_time_ms"]
    fw = [r for r in feed.funding if t0 < r["ts"] <= t_end]
    fmap = {r["ts"]: r for r in fw}

    first, last = feed.p4[0], feed.p4[-1]
    bot.enter(t0, first["open"], feed.s4[t0]["open"], args.capital)

    for bar in feed.p4:
        t, close = bar["open_time_ms"], bar["close"]
        stamp = fmap.get(t + H4_MS)  # stamp at this bar's close instant
        if stamp:
            mk = stamp["mark"]
            if not isinstance(mk, (int, float)) or not math.isfinite(mk):
                mk = close  # 4h close = price at the stamp instant
            bot.apply_funding(stamp["ts"], stamp["rate"], mk)
        sb = feed.s4.get(t)
        close_s = sb["close"] if sb else NAN
        bot.process_4h_bar(t, bar["high"], close, close_s)
        if math.isfinite(close_s):
            bot.update_monitors(t + H4_MS, close, close_s, close)

    bot.wind_down(t_end + H4_MS, last["close"], feed.s4[t_end]["close"], "end of replay")
    st = bot.st
    res = {"final_equity": round(st.R, 2), "rebalances": len(st.rebalances),
           "funding_total": round(st.funding_total, 2), "sweeps_total": round(st.sweeps_total, 2),
           "skipped_nan": st.skipped_nan}
    print("REPLAY RESULT:", json.dumps(res, indent=1))
    if args.verify:
        base = json.loads((CARRY_DIR / "carry_bt_results.json").read_text())["base_t20_close_high"]
        checks = [("final_equity", res["final_equity"], round(float(base["E_end"]), 2)),
                  ("rebalances", res["rebalances"], int(base["n_rebalances"])),
                  ("funding_total", res["funding_total"], round(float(base["funding_total"]), 2))]
        ok = True
        for name, got, want in checks:
            match = abs(got - want) <= max(0.005 * abs(want), 1.0)
            ok &= match
            print(f"  {'PASS' if match else 'FAIL'} {name}: bot={got} backtest={want}")
        print("REPLAY PARITY:", "ALL MATCH" if ok else "MISMATCH — investigate")
        sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description="BTCUSDT funding-carry paper bot (SPEC v1.1)")
    ap.add_argument("--mode", choices=["live", "replay"], required=True)
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--theta", type=float, default=THETA_BASE)
    ap.add_argument("--state-dir", default=str(BOT_DIR / "state"))
    ap.add_argument("--interval-sec", type=int, default=300)
    ap.add_argument("--enter", action="store_true", help="open the paper position now (live)")
    ap.add_argument("--once", action="store_true", help="single poll then exit (live)")
    ap.add_argument("--verify", action="store_true", help="assert replay parity vs backtest")
    args = ap.parse_args()
    replay(args) if args.mode == "replay" else live_loop(args)


if __name__ == "__main__":
    main()
