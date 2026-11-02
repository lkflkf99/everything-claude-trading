"""Runner: executes the carry backtest configurations and saves artifacts.

  RUN A (evidence): spec-literal down-sweep (q05) -> terminates at first liq.
  RUN B (proposed minimal fix): carry-only sweep + reserve backstop.
    base:                 theta=0.20, exec=close,     scan=high
    robustness (pre-registered, one-at-a-time):
      theta=0.15, theta=0.25, exec=next_open, scan=close

Outputs (research/):
  carry_bt_results.json      all configs' full result dicts
  carry_bt_equity_base.csv   daily equity curve (RUN B base)
  carry_bt_rebalances.csv    rebalance log (RUN B base)
  carry_bt_run_log.txt       consolidated console report
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from carry_backtest import run_backtest

OUT = Path(__file__).resolve().parent
LINES = []


def emit(s=""):
    print(s)
    LINES.append(str(s))


def strip(res):
    return {k: v for k, v in res.items() if not k.startswith("_")}


def core_row(name, r):
    return {
        "config": name,
        "ann_on_N_%": round(100 * r["ann_on_N"], 3),
        "ann_on_C_%": round(100 * r["ann_on_C"], 3),
        "pnl_$": r["pnl"],
        "sharpe": r["sharpe_daily_C"],
        "maxDD_%": round(100 * r["maxdd_pct"], 3),
        "t_NW10": r["t_nw10"],
        "n_rebal": r["n_rebalances"],
        "rebal_cost_$": r["rebal_costs"],
        "liq_events": r["n_liq_mark"] + r["n_liq_gap_proxy"],
        "min_liq_dist_%": round(100 * r["min_liq_dist"], 2),
        "unmet": r["unmet_shortfalls"],
    }


def main():
    # ---------------- RUN A: spec-literal evidence ----------------
    emit("=" * 88)
    emit("RUN A  spec-literal down-sweep (q=0.5), reserve backstop ON, terminate at 1st liq")
    emit("=" * 88)
    ra = run_backtest(sweep_mode="q05", reserve_backstop=True, terminate_on_liq=True,
                      collect_curve=False)
    emit(json.dumps({"terminated": ra["terminated"], "termination": ra["termination"],
                     "years": ra["years"], "pnl": ra["pnl"], "ann_on_N": ra["ann_on_N"],
                     "t_nw10": ra["t_nw10"], "n_rebalances": ra["n_rebalances"],
                     "extract_binds": ra["extract_binds"]}, indent=2, default=str))

    # ---------------- RUN B: proposed minimal fix, 5 pre-registered configs ----------------
    cfgs = {
        "base_t20_close_high": dict(theta=0.20, exec_mode="close", scan="high"),
        "theta15": dict(theta=0.15, exec_mode="close", scan="high"),
        "theta25": dict(theta=0.25, exec_mode="close", scan="high"),
        "exec_next_open": dict(theta=0.20, exec_mode="next_open", scan="high"),
        "scan_close": dict(theta=0.20, exec_mode="close", scan="close"),
    }
    results = {"RUN_A_spec_literal": strip(ra)}
    rows = []
    curves = {}
    for name, kw in cfgs.items():
        r = run_backtest(sweep_mode="carry", reserve_backstop=True, collect_curve=True, **kw)
        results[name] = strip(r)
        rows.append(core_row(name, r))
        if name == "base_t20_close_high":
            curves["eq"] = r["_eq"]
            curves["rebal"] = r["_rebal_log"]

    emit("\n" + "=" * 88)
    emit("RUN B  proposed minimal fix (carry-only sweep + reserve backstop) — 5 configs")
    emit("=" * 88)
    tbl = pd.DataFrame(rows).set_index("config")
    emit(tbl.to_string())

    base = results["base_t20_close_high"]
    emit("\n--- entry/exit (base) ---")
    emit(json.dumps({"entry": base["entry"], "exit": base["exit"]}, indent=2))
    emit("\n--- funding & flows (base) ---")
    emit(json.dumps({k: base[k] for k in
                     ["funding_total", "funding_pos", "funding_neg", "n_funding_events",
                      "n_extractions", "extract_total", "n_reserve_draws", "reserve_draw_total",
                      "fee_entry", "fee_exit", "rebal_costs", "mark_src", "funding_grid_ok",
                      "spot4h_missing", "n_gap_bars_proxy"]}, indent=2))
    emit("\n--- circuit breaker & negative stretches (base) ---")
    emit(json.dumps({"n_cb_triggers": base["n_cb_triggers"], "cb_triggers": base["cb_triggers"],
                     "n_neg_stretches": base["n_neg_stretches"],
                     "neg_stretches_top5": base["neg_stretches_top5"]}, indent=2))
    emit("\n--- liquidation monitor (base) ---")
    emit(json.dumps({k: base[k] for k in
                     ["n_liq_mark", "n_liq_gap_proxy", "min_liq_dist", "min_liq_date",
                      "min_liq_proxy", "stress_min_liq_dist"]}, indent=2))

    emit("\n--- per-year PnL (base) ---")
    py = pd.DataFrame(base["per_year"]).T
    py.index.name = "year"
    emit(py.to_string())

    emit("\n--- segments (base) ---")
    for k, v in base["segments"].items():
        emit(f"{k}: {json.dumps(v)}")

    emit("\n--- per-year / segments across robustness configs (ann_on_N) ---")
    for name in cfgs:
        r = results[name]
        seg = r["segments"]["post_breakpoint"]
        emit(f"{name:24s} post-bp ann_on_N={100*seg['ann_on_N']:.3f}%  pnl={seg['pnl']}$  "
             f"ann_full={100*r['ann_on_N']:.3f}%  minDD={100*r['maxdd_pct']:.3f}%  "
             f"liq={r['n_liq_mark']+r['n_liq_gap_proxy']}  minDist={100*r['min_liq_dist']:.2f}%")

    # consistency with quant-researcher forward estimate
    seg = base["segments"]["post_breakpoint"]
    emit(f"\nQR consistency: post-bp net ann on N = {100*seg['ann_on_N']:.3f}% "
         f"vs QR forward 3.1% CI[2.0, 4.2] -> "
         f"{'INSIDE' if 0.020 <= seg['ann_on_N'] <= 0.042 else 'OUTSIDE'}")

    # artifacts
    curves["eq"].to_csv(OUT / "carry_bt_equity_base.csv", index=False)
    curves["rebal"].to_csv(OUT / "carry_bt_rebalances.csv", index=False)
    with (OUT / "carry_bt_results.json").open("w") as fh:
        json.dump(results, fh, indent=2, default=str)
    (OUT / "carry_bt_run_log.txt").write_text("\n".join(LINES))
    emit("\nartifacts: carry_bt_results.json, carry_bt_equity_base.csv, "
         "carry_bt_rebalances.csv, carry_bt_run_log.txt")


if __name__ == "__main__":
    main()
