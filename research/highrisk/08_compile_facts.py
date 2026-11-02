"""08: Compile key market-structure facts into one JSON for the quant-researcher."""
import pandas as pd, numpy as np, json

OUT = "research/highrisk"
facts = {}

facts["overview"] = json.load(open(f"{OUT}/overview.json"))
facts["vol_distribution"] = json.load(open(f"{OUT}/vol_distribution.json"))
facts["regime_persistence"] = json.load(open(f"{OUT}/regime_persistence.json"))
facts["funding_summary"] = json.load(open(f"{OUT}/funding_summary.json"))
facts["drawdown_summary"] = json.load(open(f"{OUT}/drawdown_summary.json"))
facts["weekend_effect"] = json.load(open(f"{OUT}/weekend_effect.json"))
facts["halving_windows"] = json.load(open(f"{OUT}/halving_windows.json"))
facts["taker_flow"] = json.load(open(f"{OUT}/taker_flow_summary.json"))

ac = json.load(open(f"{OUT}/autocorr.json"))
facts["autocorr_key"] = {
    "dret_lag1_full": ac["dret_acf_lags1_30"]["1"],
    "ret4h_lag1_full": ac["ret4h_acf_lags1_30"]["1"],
    "abs_dret_acf": ac["abs_dret_acf_lag1_5_10_20"],
    "variance_ratio_daily": ac["variance_ratio_daily"],
    "weekly_acf_lag1": ac["weekly_ret_acf_lag1_4"]["1"],
    "monthly_acf_lag1": ac["monthly_ret_acf_lag1_3"]["1"],
    "dret_lag1_by_year": ac["dret_lag1_by_year"],
}

# regime grid: key cells only
grid = pd.read_csv(f"{OUT}/regime_forward_returns.csv")
g30 = grid[grid["horizon"] == "fwd_30d"]
facts["regime_grid_fwd30d"] = g30.to_dict("records")

fy = pd.read_csv(f"{OUT}/funding_yearly.csv")
facts["funding_yearly"] = fy.to_dict("records")

fc = pd.read_csv(f"{OUT}/funding_conditional_forward.csv")
facts["funding_conditional_forward"] = fc.to_dict("records")

sp = pd.read_csv(f"{OUT}/spike_reversal_events.csv")
facts["spike_reversal_events"] = sp.to_dict("records")
facts["spike_reversal_baseline"] = json.load(open(f"{OUT}/spike_reversal_baseline.json"))

tf = pd.read_csv(f"{OUT}/taker_flow_forward.csv")
facts["taker_flow_forward"] = tf.to_dict("records")

dd = pd.read_csv(f"{OUT}/drawdown_episodes.csv")
facts["top_drawdowns"] = dd.head(8).to_dict("records")

yr = pd.read_csv(f"{OUT}/yearly_stats.csv")
facts["yearly_stats"] = yr.to_dict("records")

hc = pd.read_csv(f"{OUT}/halving_cycle.csv")
facts["halving_cycle_year"] = hc.to_dict("records")

facts["caveats"] = [
    "All t-stats on multi-day forward returns are inflated by overlapping windows (fwd_7d overlaps ~7x, fwd_30d ~30x); use non-overlapping resampling or Newey-West in formal tests.",
    "Regime terciles are full-sample (characterization, not tradable as-is); tradable version must use expanding/rolling quantiles.",
    "Funding-flush crash events n=14; cycle analysis n=2 halvings; both underpowered.",
    "Data ends 2026-10-31 inside an unrecovered -38% drawdown from the 2025-10-06 peak; end-of-sample regime = low vol (~39%), low funding (~0.3bp/8h), bear/chop.",
    "Taker-buy imbalance is contemporaneously correlated with up-days; incremental value over price momentum must be tested with controls.",
]
with open(f"{OUT}/facts.json", "w") as fh:
    json.dump(facts, fh, indent=2)
print("facts.json written, keys:", list(facts.keys()))
print("size_kb:", round(len(json.dumps(facts)) / 1024, 1))
