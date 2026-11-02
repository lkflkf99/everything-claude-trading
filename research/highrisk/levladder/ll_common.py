"""ll_common: shared engine for the leverage-ladder analysis of the SHIPPED A1 book.

Question: the approved TG1x-hyst2 x VB(10,100,5) book (isolated 1x) is asked to run
at L in {1.5, 2, 3, 5, 10}. Would the gate's ACTUAL daily path have been liquidated,
and does a causal leverage condition make any rung survivable?

Conventions (locked to STRATEGY_SPEC_v1.md / bt_03_stamp_exact.py / exchange_specs.md):
- Panel date t labels the UTC kline day; close[t] prints at 00:00 UTC on day t+1.
  Decisions at close[t] execute 00:05 UTC on day t+1 (taker, 5bp per side).
- Episodes come from bt_trade_log.csv (the shipped stamp-exact fills). Entry/exit
  prices are the ACTUAL logged fills, not re-derived prices. Only intra-episode
  drift rebalances (deadband) are re-simulated per arm.
- Margin model: Binance USDT-M isolated, one-way long, whole book in one sub-account.
  Wallet WB = all cash (posted as isolated margin); equity E = WB + Q*(P - EP).
  Liquidation when WB + Q*(P-EP) < Q*P*MMR - cum, checked on 5m MARK low
  (liquidation is a mark event, exchange_specs.md section 2.3/2.6).
  Tiers from exchange_specs.md section 2.4: <=300k: MMR .004 cum 0; <=800k: .005/300;
  <=3M: .0065/1500; <=12M: .01/12000; <=70M: .02/132000. Tier chosen by segment
  notional at segment start (documented approximation; Binance re-checks tick-by-tick).
- Funding: real stamps 00/08/16 UTC from the funding CSV; WB -= Q*mark*rate.
  Entry day skips the 00:00 stamp (flat then), pays 08/16; exit day pays 00:00.
- Drift deadband (spec section 7 extended to L): at the daily 00:05 check, if the
  book is open and |Q*p/E - L_target| <= 0.05*L_target, skip; else rebalance to
  exactly L_target*E (fee on |dQ| only, QR-parity). Reduce keeps EP and crystallizes
  (Q-Q_new)*(p-EP) into WB; add blends EP. This is the shipped mechanic: it rescues
  slow grinds by deleveraging; fast crashes between daily checks still kill.
- Mark gaps (exchange_specs.md section 1): inside gaps degrade to trade-5m low/high
  proxy and flag; bars missing in BOTH series are unobservable (skipped, flagged).
- MIN_NOTIONAL 50 USDT: if L*E < 50 at a rebalance check the book closes (dust);
  flagged as economic wipeout, distinct from an exchange liquidation.

Arms: constant L in {1, 1.5, 2, 3, 5, 10} and conditional arms
  L(t) = L_max iff rv10(t) <= X AND dd_from_episode_peak(t) > -Y else 1,
  decided at close[t] (data <= close[t]), effective 00:05 on t+1. Causal only.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

HR = "research/highrisk"
OUT = "research/highrisk/levladder"
os.makedirs(OUT, exist_ok=True)

TC = 0.0005          # taker 5bp per side (QR-parity, conservative per exchange_specs)
STEP = 0.001
MIN_NOTIONAL = 50.0
E0_BOOK = 10_000.0

# (notional cap USDT, MMR, cum USDT) — exchange_specs.md §2.4, 2026-11-02 snapshot
TIERS = [
    (300_000.0, 0.004, 0.0),
    (800_000.0, 0.005, 300.0),
    (3_000_000.0, 0.0065, 1_500.0),
    (12_000_000.0, 0.010, 12_000.0),
    (70_000_000.0, 0.020, 132_000.0),
    (100_000_000.0, 0.025, 482_000.0),
]

NS_5M = np.int64(5 * 60 * 1_000_000_000)
NS_30M = np.int64(30 * 60 * 1_000_000_000)


def tier_for(notional: float):
    for cap, mmr, cum in TIERS:
        if notional <= cap:
            return mmr, cum
    return TIERS[-1][1], TIERS[-1][2]


def lp_long(wb: float, q: float, ep: float, mmr: float, cum: float) -> float:
    """Isolated long liquidation price (mark)."""
    return (wb + cum - q * ep) / (q * (mmr - 1.0))


def static_lp_distance(lev: float, mmr: float = 0.004) -> float:
    """Adverse distance from entry to LP for wallet = notional/L, cum=0."""
    return (1.0 / lev - mmr) / (1.0 - mmr)


def ns(ts: pd.Timestamp) -> int:
    return int(ts.value)


# ---------------------------------------------------------------- data loading
def load_daily() -> pd.DataFrame:
    d = pd.read_csv(f"{HR}/bt_daily.csv", index_col=0, parse_dates=True)
    d.index = d.index.normalize()
    return d


def load_episodes(daily: pd.DataFrame) -> list[dict]:
    """Reconstruct holding episodes from the shipped trade log (actual fills)."""
    tl = pd.read_csv(f"{HR}/bt_trade_log.csv", parse_dates=["exec_day"])
    eps = []
    pos = 0.0
    cur = None
    for _, r in tl.iterrows():
        day = r["exec_day"].normalize()
        prev = pos
        pos = pos + r["dq"]
        if abs(prev) < 1e-9 and abs(pos) > 1e-9:          # entry
            cur = {
                "entry_exec_day": day,
                "entry_px": float(r["price"]),
                "entry_fee": float(r["fee_usdt"]),
                "entry_notional": float(r["dq"] * r["price"]),
                "entry_qty": float(r["dq"]),
                "rebars": [],
            }
        elif cur is not None and abs(pos) < 1e-9:          # exit
            cur["exit_exec_day"] = day
            cur["exit_px"] = float(r["price"])
            cur["exit_fee"] = float(r["fee_usdt"])
            eps.append(cur)
            cur = None
        elif cur is not None:                              # deadband rebalance
            cur["rebars"].append((day, float(r["dq"]), float(r["price"])))
    if cur is not None:                                    # open at sample end
        cur["exit_exec_day"] = None
        cur["exit_px"] = None
        cur["exit_fee"] = None
        eps.append(cur)

    gate = daily["gate"]
    mvb = daily["m_vb"]
    for i, ep in enumerate(eps):
        t_in = ep["entry_exec_day"] - pd.Timedelta(days=1)   # decision date
        ep["entry_decision"] = t_in
        g, gp = gate.get(t_in, np.nan), gate.get(t_in - pd.Timedelta(days=1), np.nan)
        m, mp = mvb.get(t_in, np.nan), mvb.get(t_in - pd.Timedelta(days=1), np.nan)
        ep["entry_reason"] = "+".join(
            [s for s, c in [("gate01", g == 1 and gp == 0),
                            ("vb_rearm", m == 1 and mp == 0)] if c] or ["?"])
        if ep["exit_exec_day"] is None:
            ep["exit_reason"] = "open_eos"
            ep["exit_decision"] = None
        else:
            t_out = ep["exit_exec_day"] - pd.Timedelta(days=1)
            ep["exit_decision"] = t_out
            ep["exit_reason"] = ("gate10" if gate.get(t_out, 1) == 0 else
                                 "vb_off" if mvb.get(t_out, 1) == 0 else "?")
        ep["id"] = i + 1
    return eps


class Path5m:
    """Merged mark/trade 5m path. Mark preferred; trade proxy inside mark gaps."""

    def __init__(self):
        mk = pd.read_csv("research/data/binance_um_btcusdt_perp_mark_5m.csv",
                         parse_dates=["open_time_utc"])
        tr = pd.read_csv("research/data/binance_um_btcusdt_perp_5m.csv",
                         parse_dates=["open_time_utc"])
        mk["ns"] = mk["open_time_utc"].values.astype("datetime64[ns]").astype(np.int64)
        tr["ns"] = tr["open_time_utc"].values.astype("datetime64[ns]").astype(np.int64)
        mki = mk.set_index("ns").sort_index()
        tri = tr.set_index("ns").sort_index()
        trade_only = tri.index.difference(mki.index)
        self.ns = mki.index.values
        self.low = mki["low"].to_numpy(float)
        self.high = mki["high"].to_numpy(float)
        self.close = mki["close"].to_numpy(float)
        self.src = np.ones(len(mki), dtype=np.int8)               # 1 = mark
        if len(trade_only):
            tp = tri.loc[trade_only]
            self.ns = np.concatenate([self.ns, tp.index.values])
            self.low = np.concatenate([self.low, tp["low"].to_numpy(float)])
            self.high = np.concatenate([self.high, tp["high"].to_numpy(float)])
            self.close = np.concatenate([self.close, tp["close"].to_numpy(float)])
            self.src = np.concatenate([self.src, np.zeros(len(tp), np.int8)])
            order = np.argsort(self.ns)
            self.ns, self.low, self.high, self.close, self.src = (
                a[order] for a in (self.ns, self.low, self.high, self.close, self.src))
        self.trade_ns = tri.index.values
        self.mark_ns = mki.index.values

    def slice(self, t0_ns: int, t1_ns: int):
        i0 = int(np.searchsorted(self.ns, t0_ns))
        i1 = int(np.searchsorted(self.ns, t1_ns))
        return i0, i1


def load_stamps() -> pd.DataFrame:
    f = pd.read_csv("research/data/binance_um_btcusdt_perp_funding.csv",
                    parse_dates=["funding_time_utc"]).set_index("funding_time_utc").sort_index()
    f["funding_rate"] = f["funding_rate"].astype(float)
    f["mark_price"] = pd.to_numeric(f["mark_price"], errors="coerce")
    return f


def load_p05() -> dict:
    m5 = pd.read_csv("research/data/binance_um_btcusdt_perp_5m.csv",
                     usecols=["open_time_utc", "open"], parse_dates=["open_time_utc"])
    m5 = m5.set_index("open_time_utc").sort_index()
    b = m5[(m5.index.hour == 0) & (m5.index.minute == 5)]["open"]
    return {d.normalize(): float(v) for d, v in b.items()}


# ---------------------------------------------------------------- book engine
class Book:
    """Chained margin simulation of the whole strategy book across episodes.

    Per exec day d (decision date t_dec = d-1):
      1. 00:00 funding stamp on pre-trade Q; equity sample at close[t_dec]
      2. scan [00:00, 00:05) for liquidation
      3. 00:05 entry / exit / deadband rebalance (decided at close[t_dec])
      4. scan [00:05, 08:00); 08:00 stamp
      5. scan [08:00, 16:00); 16:00 stamp
      6. scan [16:00, next 00:00)
    Each scan uses the wallet state in force during that segment.
    """

    def __init__(self, daily: pd.DataFrame, eps: list[dict], path: Path5m,
                 stamps: pd.DataFrame, p05: dict, arm: dict):
        self.daily = daily
        self.eps = eps
        self.path = path
        self.arm = arm
        self.close = daily["close"]
        self.rv10 = daily["rv10"]
        self.p05 = p05
        self.stamps = {}
        for ts, r in stamps.iterrows():
            self.stamps.setdefault(ts.normalize(), []).append(
                (ts.hour, float(r["funding_rate"]), r["mark_price"]))
        self.WB = E0_BOOK
        self.Q = 0.0
        self.EP = np.nan
        self.dead = False
        self.death = None
        self.equity_samples = []     # (decision_date, E)
        self.funding_flows = []      # (day, usdt signed)
        self.n_trades = 0
        self.fees_total = 0.0
        self.ep_results = []
        self.flags = []
        self._ctx = None             # per-episode running context

    # ---- helpers -----------------------------------------------------
    def path_end_day(self) -> pd.Timestamp:
        return pd.Timestamp(self.path.ns[-1]).normalize()

    def equity(self, p: float) -> float:
        return self.WB if self.Q == 0 else self.WB + self.Q * (p - self.EP)

    def target_leverage(self, t_dec: pd.Timestamp, peak: float | None) -> float:
        """Leverage decided at close[t_dec] (causal inputs only)."""
        a = self.arm
        if a["kind"] == "const":
            return a["L"]
        ok = True
        if a["X"] is not None:
            r = self.rv10.get(t_dec, np.nan)
            ok = ok and np.isfinite(r) and r <= a["X"]
        if a["Y"] is not None:
            c = self.close.get(t_dec, np.nan)
            ok = ok and peak is not None and np.isfinite(c) and c > (1 - a["Y"]) * peak
        return a["L"] if ok else 1.0

    def _stamp_flow(self, day: pd.Timestamp, hour: int, px_fallback: float):
        if self.Q == 0:
            return
        for h, rate, mark in self.stamps.get(day, []):
            if h != hour:
                continue
            mk = mark if np.isfinite(mark) else px_fallback
            flow = -self.Q * mk * rate
            self.WB += flow
            self.funding_flows.append((day, flow))
            if self._ctx is not None:
                self._ctx["funding"] += flow

    def _scan(self, t0: int, t1: int, when: str) -> bool:
        """Liquidation scan over [t0,t1). True if the book died."""
        if self.Q == 0 or t1 <= t0:
            return False
        p = self.path
        i0, i1 = p.slice(t0, t1)
        if i1 <= i0:
            if t1 - t0 > NS_30M:
                self.flags.append(f"unobserved@{when}")
            return False
        c0 = p.close[i0]
        notional = self.Q * (c0 if np.isfinite(c0) else self.EP)
        mmr, cum = tier_for(notional)
        lp = lp_long(self.WB, self.Q, self.EP, mmr, cum)
        lows = p.low[i0:i1]
        hit = np.flatnonzero(lows < lp)
        if (p.src[i0:i1] == 0).any():
            self.flags.append(f"trade_proxy@{when}")
        if hit.size == 0:
            # track LP-distance headroom for reporting
            if self._ctx is not None:
                min_low = float(np.min(lows))
                adv = 1.0 - min_low / self.EP
                if adv > self._ctx["max_adv"]:
                    self._ctx["max_adv"] = adv
                    self._ctx["max_adv_time"] = str(pd.Timestamp(p.ns[i0 + int(np.argmin(lows))]))
            return False
        k = int(hit[0])
        self.dead = True
        self.death = {
            "time": str(pd.Timestamp(p.ns[i0 + k])),
            "lp": float(lp), "mark_low": float(lows[k]),
            "wb": float(self.WB), "q": float(self.Q), "ep": float(self.EP),
            "where": when, "arm": self.arm["name"],
            "proxy_bar": bool(p.src[i0 + k] == 0),
            "episode": self._ctx["ep"]["id"] if self._ctx else None,
        }
        self.WB = 0.0
        self.Q = 0.0
        return True

    def _enter(self, px: float, L: float):
        E = self.WB
        q = np.floor(L * E / px / STEP) * STEP
        fee = q * px * TC
        self.WB = E - fee
        self.fees_total += fee
        self.Q = q
        self.EP = px
        self.n_trades += 1

    def _exit(self, px: float):
        fee = self.Q * px * TC
        self.WB += self.Q * (px - self.EP) - fee
        self.fees_total += fee
        self.Q = 0.0
        self.EP = np.nan
        self.n_trades += 1

    def _rebalance(self, day: pd.Timestamp, L_tgt: float):
        p = self.p05.get(day, np.nan)
        if not np.isfinite(p):
            self.flags.append(f"no_p05@{day.date()}")
            return
        E = self.equity(p)
        if E <= 0 or L_tgt * E < MIN_NOTIONAL:
            self.dead = True
            self.death = {"time": f"{day.date()} 00:05", "where": "dust_or_negative_equity",
                          "E": float(E), "wb": float(self.WB), "arm": self.arm["name"],
                          "episode": self._ctx["ep"]["id"] if self._ctx else None}
            self.WB, self.Q = 0.0, 0.0
            return
        ratio = self.Q * p / E
        if abs(ratio - L_tgt) <= 0.05 * L_tgt:
            return
        q_new = np.floor(L_tgt * E / p / STEP) * STEP
        fee = abs(q_new - self.Q) * p * TC
        if q_new < self.Q:                      # reduce: crystallize, keep EP
            self.WB += (self.Q - q_new) * (p - self.EP)
        else:                                   # add: blend EP
            self.EP = (self.Q * self.EP + (q_new - self.Q) * p) / q_new
        self.WB -= fee
        self.fees_total += fee
        self.Q = q_new
        self.n_trades += 1
        if self._ctx is not None:
            self._ctx["rebalances"] += 1

    def _close_ctx(self, day, reason):
        if self._ctx is None:
            return
        c = self._ctx
        c["exit_reason_sim"] = reason
        c["E_end"] = self.WB
        self.ep_results.append(c)
        self._ctx = None

    # ---- main loop ----------------------------------------------------
    def run(self):
        daily = self.daily
        entry_on = {ep["entry_exec_day"]: ep for ep in self.eps}
        exit_on = {ep["exit_exec_day"]: ep for ep in self.eps if ep["exit_exec_day"] is not None}
        end_day = self.path_end_day()
        last_day = max((ep["exit_exec_day"] or end_day) for ep in self.eps)
        d = daily.index[0] + pd.Timedelta(days=1)   # flat book from panel start
        peak = None
        while d <= last_day and not self.dead:
            t_dec = d - pd.Timedelta(days=1)
            c_fb = self.close.get(t_dec, np.nan)
            d0 = ns(d)
            # 1) 00:00 stamp on pre-trade Q, then equity sample at close[t_dec]
            self._stamp_flow(d, 0, c_fb)
            if t_dec in daily.index:
                self.equity_samples.append((t_dec, self.equity(c_fb)))
            # 2) pre-trade segment
            if self._scan(d0, d0 + NS_5M, f"pre@{d.date()}"):
                break
            # 3) 00:05 trade
            if d in entry_on:
                ep = entry_on[d]
                L = self.target_leverage(t_dec, c_fb)   # dd=0 at entry -> passes Y
                self._enter(ep["entry_px"], L)
                peak = c_fb
                self._ctx = {
                    "ep": ep, "ep_id": ep["id"], "arm": self.arm["name"],
                    "entry_day": str(d.date()), "L_entry": L,
                    "E_entry": self.WB, "minE_ratio": 1.0, "max_adv": 0.0,
                    "max_adv_time": None, "funding": -ep["entry_fee"],
                    "rebalances": 0,
                }
            elif d in exit_on and self.Q > 0:
                self._exit(exit_on[d]["exit_px"])
                self._close_ctx(d, exit_on[d]["exit_reason"])
                peak = None
            elif self.Q > 0:
                L_tgt = self.target_leverage(t_dec, peak)
                self._rebalance(d, L_tgt)
            if self.dead:
                break
            # 4-6) post-trade segments + stamps
            t08, t16 = d0 + 8 * 3600 * 10**9, d0 + 16 * 3600 * 10**9
            nxt = d0 + 24 * 3600 * 10**9
            if self._scan(d0 + NS_5M, t08, f"m@{d.date()}"): break
            self._stamp_flow(d, 8, c_fb)
            if self._scan(t08, t16, f"a@{d.date()}"): break
            self._stamp_flow(d, 16, c_fb)
            if self._scan(t16, nxt, f"e@{d.date()}"): break
            # episode tracking at day end
            if self._ctx is not None and np.isfinite(c_fb):
                E = self.equity(c_fb)
                r = E / self._ctx["E_entry"]
                if r < self._ctx["minE_ratio"]:
                    self._ctx["minE_ratio"] = float(r)
                peak = max(peak, c_fb) if peak is not None else c_fb
            d = d + pd.Timedelta(days=1)
        # book death or open episode close-out
        if self.dead:
            if self._ctx is not None:
                self._ctx["exit_reason_sim"] = ("LIQUIDATED" if self.death and "lp" in self.death
                                                else "dust_or_negative")
                self._ctx["E_end"] = 0.0
                self.ep_results.append(self._ctx)
                self._ctx = None
            self.end_equity = 0.0
        else:
            if self._ctx is not None:   # open episode at sample end
                p_end = float(self.path.close[-1])
                self._ctx["exit_reason_sim"] = "open_eos"
                self._ctx["E_end"] = self.equity(p_end)
                self.ep_results.append(self._ctx)
                self._ctx = None
                self.end_equity = self.equity(p_end)
            else:
                self.end_equity = self.WB
        return self

    # ---- reporting ----------------------------------------------------
    def equity_curve(self) -> pd.Series:
        s = pd.Series(dict(self.equity_samples)).sort_index()
        return s

    def perf(self, skip: int = 200):
        s = self.equity_curve()
        if skip:
            s = s.iloc[skip:]
        r = s.pct_change().dropna()
        n = len(s)
        if n < 2:
            return {"cagr": np.nan, "mdd": np.nan, "sharpe": np.nan, "n": n}
        yrs = n / 365.0
        cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1 if s.iloc[0] > 0 else -1.0
        mdd = float((s / s.cummax() - 1).min())
        sharpe = float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else np.nan
        return {"cagr": float(cagr), "mdd": mdd, "sharpe": sharpe, "n": n}

    def funding_per_year(self) -> dict:
        if not self.funding_flows:
            return {}
        ff = pd.DataFrame(self.funding_flows, columns=["day", "flow"])
        ff["year"] = pd.to_datetime(ff["day"]).dt.year
        eq = self.equity_curve()
        out = {}
        for y, g in ff.groupby("year"):
            soy = eq[str(y)].iloc[0] if len(eq[str(y)]) else np.nan
            out[int(y)] = {"usdt": float(g["flow"].sum()),
                           "pct_soy": 100 * float(g["flow"].sum()) / float(soy)
                           if np.isfinite(soy) and soy else np.nan}
        return out
