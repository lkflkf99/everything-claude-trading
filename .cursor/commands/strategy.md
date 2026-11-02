---
description: 从概念到实现，设计一套系统化交易策略
---

根据用户的消息设计一套系统化交易策略。遵循 `.cursor/rules/trading-workflow.mdc`。

用 Task 工具一次委派一步。将 `subagent_type` 设为下面的名称。每个子代理都从空白上下文开始，因此要带上用户请求和此前的全部发现。等当前结果出来后再进行下一步。若某个具名子代理不可用，阅读 `.cursor/agents/<name>.md`，并在这里完成该步骤。

1. `crypto-defi-analyst` — 仅当想法属于加密资产或 DeFi。覆盖市场结构、链上背景、协议风险，以及收益从哪里来。阅读 `.cursor/skills/` 中相关技能（`defi-protocols`、`on-chain-analytics`、`tokenomics`、`yield-farming`、`crypto-derivatives`、`stablecoin-analysis`、`mev-strategies` 或 `cross-chain-arbitrage`）。
2. 期权，仅当想法是美股或指数期权。先运行 `derivatives-analyst`；观点是隐含波动率、偏斜、期限结构或某个事件时，再运行 `volatility-trader`；然后运行 `options-strategist`。按适用情况阅读 `black-scholes`、`binomial-trees`、`vol-surfaces`、`vol-trading`、`hedging-strategies` 和 `greeks-management`。美式个股期权要用允许提前行权的树模型。然后继续下面的步骤。
3. `quant-researcher` — 说明信号在统计上是否可用，以及什么结果会证伪它。想法对应时，阅读 `momentum-strategies`、`mean-reversion` 或 `trend-following`。
4. `algo-strategist` — 入场、出场、仓位和再平衡规则。阅读 `position-sizing`。
5. `backtesting-engineer` — 滚动前进（walk-forward）方案、成本假设和过拟合检查。阅读 `walk-forward-optimization`、`overfitting-prevention` 和 `strategy-evaluation`。除非本工作区的代码真的跑过回测，否则不要声称回测已经运行。
6. `risk-manager` — 回撤、尾部风险和限额。阅读 `drawdown-management`。期权还要阅读 `greeks-management`。这一步可以否决策略。若被否决，停止。
7. `execution-specialist` — 滑点、费用、交易场所和买卖价差。用户询问如何交易该策略时包含这一步。
8. `regulatory-compliance` — 仅当用户要求部署或实盘交易。未通过则停止。

然后用一份规格回答：

- 信号，以及什么会证伪它
- 入场、出场和仓位规则
- 风险限额，以及 risk-manager 是通过还是否决
- 回测方案，含成本。把方案和实际算出来的结果分开写
- 若执行了执行步骤，写上执行说明
- 仍未核实的内容

不要下达实盘订单。不要编造价格或业绩数字。
