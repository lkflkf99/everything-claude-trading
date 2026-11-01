---
description: Design a systematic trading strategy from concept to implementation
---

Design a systematic trading strategy from the user's message. Follow `.cursor/rules/trading-workflow.mdc`.

Delegate with the Task tool, one step at a time. Set `subagent_type` to the name below. Each subagent starts fresh, so include the user's request and every prior finding. Wait for each result before the next step. If a named subagent is unavailable, read `.cursor/agents/<name>.md` and do that step here.

1. `crypto-defi-analyst` — only when the idea is crypto or DeFi. Cover market structure, on-chain context, protocol risk, and where any yield comes from. Read the relevant skill in `.cursor/skills/` (`defi-protocols`, `on-chain-analytics`, `tokenomics`, `yield-farming`, `crypto-derivatives`, `stablecoin-analysis`, `mev-strategies`, or `cross-chain-arbitrage`).
2. Options, only when the idea is a US stock or index option. Run `derivatives-analyst`, then `volatility-trader` when the view is implied vol, skew, term structure, or an event, then `options-strategist`. Read `black-scholes`, `binomial-trees`, `vol-surfaces`, `vol-trading`, `hedging-strategies`, and `greeks-management` as they apply. Use a tree that allows early exercise for American single-stock options. Then continue below.
3. `quant-researcher` — say whether the signal is statistically usable and what would falsify it. Read `momentum-strategies`, `mean-reversion`, or `trend-following` when the idea matches one of them.
4. `algo-strategist` — entry, exit, position sizing, and rebalance rules. Read `position-sizing`.
5. `backtesting-engineer` — a walk-forward plan, cost assumptions, and overfitting checks. Read `walk-forward-optimization`, `overfitting-prevention`, and `strategy-evaluation`. Do not claim a backtest ran unless code in this workspace actually ran it.
6. `risk-manager` — drawdown, tail risk, and limits. Read `drawdown-management`. For options, also read `greeks-management`. This step may reject the strategy. Stop if it does.
7. `execution-specialist` — slippage, fees, venue, and the bid-ask spread. Include this when the user asks how to trade the strategy.
8. `regulatory-compliance` — only if the user asks to deploy or trade live. Stop if it fails.

Then answer in one spec:

- Signal and what would falsify it
- Entry, exit, and sizing rules
- Risk limits, and whether risk-manager passed or rejected
- Backtest plan, with costs. Separate a plan from a result that was actually computed
- Execution notes when that step ran
- What is still unverified

Do not place live orders. Do not invent prices or performance numbers.
