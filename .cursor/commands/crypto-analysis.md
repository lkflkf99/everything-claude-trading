---
description: Analyze a crypto asset, DeFi protocol, on-chain metrics, or yield opportunity
---

Analyze the crypto asset, protocol, or yield in the user's message. Follow `.cursor/rules/trading-workflow.mdc`.

Delegate with the Task tool, one step at a time. Set `subagent_type` to the name below. Each subagent starts fresh, so include the user's request and every prior finding. Wait for each result before the next step. If a named subagent is unavailable, read `.cursor/agents/<name>.md` and do that step here.

1. `crypto-defi-analyst` — asset overview, on-chain context, tokenomics, protocol mechanics, and yield source. Read the relevant skills in `.cursor/skills/`: `on-chain-analytics`, `tokenomics`, `defi-protocols`, `yield-farming`, `crypto-derivatives`, `stablecoin-analysis`, `mev-strategies`, and `cross-chain-arbitrage`. Use only the ones that fit the question.
2. `risk-manager` — smart-contract, liquidity, concentration, depeg, and market risk. This step may reject the idea. Stop if it does.
3. `execution-specialist` — venue, slippage, gas, and MEV. Include this when the user asks how to trade or size a position.

Then answer with:

- What the asset or protocol is and where the yield or edge comes from
- The risk-manager verdict
- What is still unverified
- No live order

Do not invent TVL, APY, flows, or prices. Label any figure you could not verify.
