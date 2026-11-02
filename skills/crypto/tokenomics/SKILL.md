# 代币经济（tokenomics）分析

## 何时启用
- 评估代币的供给（supply）动态、排放（emission）时间表与价值捕获（value accrual）机制
- 评估归属（vesting）解锁（unlock）时间表及其潜在的市场影响
- 分析通胀（inflation）/通缩（deflation）机制与销毁（burn）机制
- 比较治理代币（governance token）设计与手续费分配（fee distribution）模型
- 对新代币发行、空投（airdrop）或协议激励计划（incentive program）做尽职调查（due diligence）

## 核心概念

### 供给框架

**供给定义：**
- **最大供给（max supply）** — 对将来会存在的代币总量所设的硬顶（hard cap）（BTC：21M；并非所有代币都设有上限）
- **总供给（total supply）** — 已铸造（mint）代币减去已销毁代币（包含锁定/尚未归属的代币）
- **流通供给（circulating supply）** — 可在公开市场上交易的代币
- **完全稀释估值（fully diluted valuation, FDV）** — 价格 * 最大供给（若没有最大供给，则使用总供给）；代表最坏情形下的稀释（dilution）
- **市值/完全稀释估值比率（MC/FDV ratio）** — 流通市值（circulating market cap）/ FDV；比率偏低意味着未来存在显著稀释

**关键洞察：** 一个市值为 $100M、FDV 为 $2B 的代币，尚有 95% 的供给未进入流通。除非需求增长快于供给通胀，否则这一供给悬置（overhang）会抑制长期价格升值。

### 排放与通胀

**排放时间表：**
- **固定时间表（fixed schedule）** — 预先确定且不可更改（immutable）（BTC 每 210,000 个区块（block）减半（halving）一次）
- **治理控制（governance-controlled）** — 社区对排放速率投票（许多去中心化金融（DeFi）协议）
- **需求驱动（demand-based）** — 排放依据协议指标调整（合并（Merge）后的 Ethereum：发行量（issuance）~ 质押（staking）参与度）
- **尾部排放（tail emission）** — 初始分配结束之后的小额永久性通胀（Monero：每个区块永久 0.6 XMR）

**通胀率计算：**
```
Annual inflation = (new tokens minted per year) / circulating supply
Real inflation = nominal inflation - burn rate
Effective inflation = real inflation adjusted for staking lockup
```

**通胀影响框架：**
- 年化 <2%：影响可忽略，与黄金相当
- 年化 2-10%：中等稀释，必须由需求增长或质押收益（staking yield）抵消
- 年化 10-50%：激进稀释，常见于早期 DeFi；除非总锁仓价值（total value locked, TVL）增长更快，否则价格通常下跌
- 年化 >50%：不可持续；通常是挖提卖（farm-and-dump）动态

### 归属时间表

**标准归属组成部分：**
- **悬崖期（cliff）** — 任何代币解锁之前的期间（通常为 6-12 个月）
- **线性归属（linear vesting）** — 悬崖期之后，代币随时间按比例解锁
- **解锁事件（unlock event）** — 离散的大额解锁（例如，代币生成事件（token generation event, TGE）时解锁 25%，其后 24 个月内按月解锁）

**市场影响评估：**
```
Unlock impact score = (tokens unlocking / daily trading volume) * recipient_sell_probability

按类别划分的接收方卖出概率（recipient sell probability）：
- 团队/创始人（team/founder）：30-50%（有持有激励，但需要流动性）
- 风险投资机构/投资者（VC/investor）：50-80%（负有返还资本的任务，经常对冲（hedge））
- 生态/社区（ecosystem/community）：10-30%（通常是较小的持有者，行为混杂）
- 国库（treasury）：5-15%（通常是程序性支出，而不是在市场上卖出）
```

**归属中的危险信号（red flag）：**
- 多个大额解锁集中在同一个月
- 团队分配 > 总供给的 25%
- 投资者成本基础（cost basis）远低于当前价格（卖出激励很高）
- 顾问代币（advisory token）没有锁定期（lockup）
- 与代币价格里程碑挂钩的归属加速条款（vesting acceleration clause）

### 价值捕获机制

**手续费分配模型：**
- **直接手续费分成（direct fee sharing）** — 协议手续费分配给代币质押者（例如，GMX：手续费的 30% 分配给 GMX 质押者）
- **回购并分配（buyback and distribute）** — 协议在市场上买入代币，再分配给质押者
- **回购并销毁（buyback and burn）** — 协议买入并销毁代币，从而减少供给（通缩）
- **费用开关（fee switch）** — 治理（governance）可以激活手续费分成（Uniswap：费用开关存在，但尚未激活）
- **投票托管代币模型（veToken model）** — 锁定代币以换取投票权（voting power）与手续费分成（Curve：veCRV）

**价值捕获分析：**
```
Protocol P/E = FDV / annualized protocol revenue
Protocol P/S = FDV / annualized protocol fees
Token holder yield = fees distributed to stakers / staked token market cap
Real yield = yield from actual revenue (not token emissions)
```

### 治理代币经济学

**治理代币的功能：**
1. 对协议参数投票（利率、抵押因子（collateral factor））
2. 手续费分配权
3. 国库分配决策
4. 协议升级批准
5. 计量器（gauge）/排放导向（emission directing）（Curve 模型）

**治理代币的估值驱动因素：**
- 收入捕获（revenue capture）（当前收入，以及经由费用开关实现的潜在收入）
- 每枚代币对应的国库价值
- 投票权价值（贿赂市场（bribery market），例如 Votium，直接为治理权力定价）
- 增长期权性（growth optionality）（新产品、新的链、合作关系）

## 方法论

### 代币评估流程
1. **绘制供给时间表** — 画出未来 5 年进入流通的代币
2. **识别解锁事件** — 在日历上标出主要的归属悬崖期，并计算相对于成交量的影响
3. **计算真实通胀（real inflation）** — 从毛排放（gross emission）中减去销毁与永久锁定（permanent lockup）
4. **评估价值捕获** — 量化手续费收入、分配机制，以及代币持有人捕获率（capture rate）
5. **比较估值** — 以市盈率（P/E）、市销率（P/S）以及 FDV/收入为基准，对照可比协议
6. **建立情景模型** — 牛市情景（bull case）（需求增长快于供给）、基准情景（base case）、熊市情景（bear case）（排放抛售（emission dumping））

### 供给冲击（supply shock）分析
```
1. 以美元口径计算每日排放速率
2. 与平均每日成交量比较
3. 排放/成交量比率 > 5%：存在显著卖压（sell pressure）
4. 识别天然买家（质押者、治理锁定者（governance locker）、国库）
5. 净卖压（net selling pressure）= 排放 - 天然吸收（natural absorption）
6. 将供给时间表对照需求增长情景进行投影
```

## 示例

### 示例 1：通缩分析（合并后的 ETH）
```
合并前的 ETH 通胀：年化 ~4.3%（工作量证明（proof of work, PoW）发行）
合并后的 ETH：
- 权益证明（proof of stake, PoS）发行：年化 ~0.5%（随质押比率变化）
- EIP-1559 销毁：年化 ~0.5-2.0%（随网络使用量变化）
- 净通胀（net inflation）：-0.5% 至 +0.3%（高使用量期间经常处于通缩）

评估：ETH 实现了“超声货币（ultrasound money）”叙事。
高活跃期间，供给在结构上下降。
正反馈循环（positive feedback loop）：使用越多 = 销毁越多 = 供给越少 = 价格越高。
关键风险：若二层网络（layer 2, L2）捕获大部分活动，一层网络（layer 1, L1）的销毁就会下降。
```

### 示例 2：归属解锁的影响
```
代币：PROJECT_X
当前价格：$5.00
流通供给：100M 枚代币（$500M 市值（MC））
FDV：$2.5B（500M 最大供给）
每日成交量：$20M

即将到来的解锁：50M 枚代币（风险投资轮的价格为 $0.50/枚）
风险投资成本基础：$0.50（按当前价格计算为 10x 利润）
预期卖压：50M * $5 * 60% 卖出概率 = $150M

分析：
- $150M 的卖盘进入 $20M 的每日成交量 = 7.5 天的成交量
- 即使有 20% 的市场冲击（market impact）被吸收，价格压力依然严重
- 历史模式：类似的解锁会造成 20-40% 的回撤（drawdown）
- 策略：在解锁前 2 周减仓，待卖压消退后重新进入
  （通常为解锁后 2-4 周）
```

### 示例 3：veToken 模型估值
```
协议：Curve Finance
年化交易手续费：$150M
CRV 质押者份额：50% = $75M 分配给 veCRV 持有者
veCRV 总量：500M CRV 被锁定（平均 3 年）
veCRV 市值：$250M

质押收益：$75M / $250M = 30% 真实收益（real yield）
额外价值：贿赂收入（Votium 上年化 $100M+）
总收益：($75M + $100M) / $250M = 70%

评估：高真实收益意味着低估（undervaluation），或者
风险溢价（risk premium）很高。风险包括治理攻击（governance attack）、
竞争性自动做市商（automated market maker, AMM），以及围绕
贿赂机制的监管不确定性（regulatory uncertainty）。
```

## 质量门禁（quality gate）

在依据代币经济做出投资决策之前，请核实：

- [ ] 供给时间表数据来自已验证的智能合约（smart contract），而不仅仅是白皮书（whitepaper）中的声明
- [ ] 归属合约不可更改，或者对变更设有透明的治理
- [ ] FDV 计算包含全部可能的供给来源（国库、生态基金（ecosystem fund）、未来排放）
- [ ] 销毁机制可以在链上（on-chain）核实，而不仅仅是在文档中声称
- [ ] 手续费分配已经上线且可审计（auditable），而不是未来的“费用开关”承诺
- [ ] 通胀计算计入全部排放来源（质押奖励（staking reward）、流动性挖矿（liquidity mining）、赠款（grant））
- [ ] 已评估治理中心化（centralization）——一小群持有者能否控制关键决策？
- [ ] 可比协议的估值处于同类比较（apples-to-apples）的基础之上（相同指标、相同的链、相似阶段）
- [ ] 代币效用（token utility）是真实的，并且不容易在没有该代币的情况下被复制
- [ ] 已考虑手续费分配机制的法律/监管地位（证券分类（securities classification）风险）
