---
description: 分析加密资产、DeFi 协议、链上指标或收益机会
---

分析用户消息中的加密资产、协议或收益。遵循 `.cursor/rules/trading-workflow.mdc`。

用 Task 工具一次委派一步。将 `subagent_type` 设为下面的名称。每个子代理都从空白上下文开始，因此要带上用户请求和此前的全部发现。等当前结果出来后再进行下一步。若某个具名子代理不可用，阅读 `.cursor/agents/<name>.md`，并在这里完成该步骤。

1. `crypto-defi-analyst` — 资产概览、链上背景、代币经济、协议机制和收益来源。阅读 `.cursor/skills/` 中相关技能：`on-chain-analytics`、`tokenomics`、`defi-protocols`、`yield-farming`、`crypto-derivatives`、`stablecoin-analysis`、`mev-strategies` 和 `cross-chain-arbitrage`。只使用与问题相符的技能。
2. `risk-manager` — 智能合约、流动性、集中度、脱锚和市场风险。这一步可以否决该想法。若被否决，停止。
3. `execution-specialist` — 交易场所、滑点、gas 和 MEV。用户询问如何交易或如何确定仓位时包含这一步。

然后回答：

- 该资产或协议是什么，收益或优势从哪里来
- risk-manager 的结论
- 仍未核实的内容
- 不下实盘订单

不要编造 TVL、APY、资金流或价格。任何无法核实的数字都要标明。
