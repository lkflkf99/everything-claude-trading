---
description: Price and structure a US equity or index options trade
---

Analyze the US stock or index option in the user's message. Follow `.cursor/rules/trading-workflow.mdc`.

Use only prices, strikes, expiries, and implied vols the user supplied. If the chain is missing, say what is missing and stop before a priced recommendation. Do not invent quotes. American single-stock options need a tree that allows early exercise. Do not present a European Black-Scholes price as the market price.

Delegate with the Task tool, one step at a time. Set `subagent_type` to the name below. Each subagent starts fresh, so include the user's request and every prior finding. Wait for each result before the next step. If a named subagent is unavailable, read `.cursor/agents/<name>.md` and do that step here.

1. `derivatives-analyst` — price the structure and compute delta, gamma, vega, and theta from the quotes given. Read `black-scholes`, `binomial-trees`, and `vol-surfaces` as they apply.
2. `volatility-trader` — only when the user asks about skew, term structure, implied versus realized vol, or an event such as earnings. Read `vol-trading` and `vol-surfaces`.
3. `options-strategist` — choose the structure for the user's view and max loss: vertical, condor, calendar, hedge, or a single option. Read `hedging-strategies` when the user wants a hedge.
4. `risk-manager` — max loss, gap risk, margin, and the Greeks. Read `greeks-management` and `drawdown-management`. This step may reject the trade. Stop if it does.
5. `execution-specialist` — the spread and how to get filled. Include this when the user asks how to trade it.
6. `quant-researcher`, then `algo-strategist`, then `backtesting-engineer` — only when the user wants a repeating rule rather than one trade. Do not claim a backtest ran unless code in this workspace actually ran it.
7. `regulatory-compliance` — only if the user asks to deploy or trade live. Stop if it fails.

Then answer with:

- The structure, strikes, and expiry
- Price and Greeks, each labeled as computed from the user's quotes or not verified
- Max loss and the risk-manager verdict
- What is still missing from the chain

Do not place live orders.
