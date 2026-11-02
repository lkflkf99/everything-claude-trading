---
description: 为美股或指数期权交易定价并设计结构
---

分析用户消息中的美股或指数期权。遵循 `.cursor/rules/trading-workflow.mdc`。

只使用用户提供的价格、行权价、到期日和隐含波动率。若期权链缺失，说明缺什么，并在给出定价建议之前停止。不要编造报价。美式个股期权需要允许提前行权的树模型。不要把欧式 Black-Scholes 价格当成市场价格。

用 Task 工具一次委派一步。将 `subagent_type` 设为下面的名称。每个子代理都从空白上下文开始，因此要带上用户请求和此前的全部发现。等当前结果出来后再进行下一步。若某个具名子代理不可用，阅读 `.cursor/agents/<name>.md`，并在这里完成该步骤。

1. `derivatives-analyst` — 为结构定价，并根据给出的报价计算 delta、gamma、vega 和 theta。按适用情况阅读 `black-scholes`、`binomial-trees` 和 `vol-surfaces`。
2. `volatility-trader` — 仅当用户询问偏斜、期限结构、隐含波动率相对已实现波动率，或财报等事件。阅读 `vol-trading` 和 `vol-surfaces`。
3. `options-strategist` — 按用户的观点和最大亏损选择结构：垂直价差、铁鹰（condor）、日历价差、对冲，或单腿期权。用户需要对冲时阅读 `hedging-strategies`。
4. `risk-manager` — 最大亏损、跳空风险、保证金和希腊值（Greeks）。阅读 `greeks-management` 和 `drawdown-management`。这一步可以否决交易。若被否决，停止。
5. `execution-specialist` — 价差以及如何成交。用户询问如何交易时包含这一步。
6. `quant-researcher`，然后 `algo-strategist`，然后 `backtesting-engineer` — 仅当用户要的是一条重复执行的规则，而不是单笔交易。除非本工作区的代码真的跑过回测，否则不要声称回测已经运行。
7. `regulatory-compliance` — 仅当用户要求部署或实盘交易。未通过则停止。

然后回答：

- 结构、行权价和到期日
- 价格和希腊值，每一项都标明是根据用户报价算出的，还是未核实
- 最大亏损，以及 risk-manager 的结论
- 期权链仍缺少什么

不要下达实盘订单。
