# 流动性挖矿（yield farming）分析

## 何时启用
- 评估跨协议（protocol）、跨链（chain）的去中心化金融（DeFi）收益（yield）机会
- 计算计入无常损失（impermanent loss，IL）与复利（compounding）效应之后的真实年化收益率（APY）/年化利率（APR）
- 评估提供流动性（liquidity provision）策略的风险调整后回报（risk-adjusted return）
- 比较真实收益（real yield，来自协议收入）与排放补贴收益（emission-subsidized yield）
- 设计流动性提供者（LP）头寸（position）管理策略，包括入场（entry）、退出（exit）与再平衡（rebalancing）

## 核心概念

### APY 与 APR

**年化利率（APR）：**
- 不含复利的单利（simple interest）利率
- APR = (periodic_rate) * (periods_per_year)
- 用于借款成本（borrowing cost）与基础排放利率（base emission rate）

**年化收益率（APY）：**
- 包含复利效应
- APY = (1 + periodic_rate)^periods_per_year - 1
- 每日复利（daily compounding）：APY = (1 + APR/365)^365 - 1
- 在 50% APR 下：每日复利得到约 64.8% APY
- 在 100% APR 下：每日复利得到约 171.5% APY
- 在 1000% APR 下：每日复利得到约 2,191,614% APY（这说明极端 APY 为何具有误导性）

**自动复利（auto-compounding）的成本/收益：**
- 在 Ethereum 上，每次复利的燃料费（gas）成本为 $5-50，取决于复杂程度
- 盈亏平衡（break-even）：只有当赚到的收益 > 燃料费成本时，才进行复利
- 最优频率（optimal frequency）= sqrt(2 * gas_cost * periods_per_year / (principal * APR))
- 收益聚合器（yield aggregator）（Yearn、Beefy）把燃料费成本分摊（socialize）给全体存款人（depositor）

### 无常损失（IL）

**定义：** 以 LP 形式持有代币，与仅在钱包（wallet）中持有这些代币，二者之间的组合价值（portfolio value）差额。

**恒定乘积自动做市商（constant product AMM）（Uniswap v2）IL 公式：**
```
IL = 2 * sqrt(price_ratio) / (1 + price_ratio) - 1

其中 price_ratio = new_price / initial_price

价格变动 -> IL：
  1.25x（上涨 25%）-> -0.6%
  1.50x（上涨 50%）-> -2.0%
  2.00x（上涨至 2 倍）-> -5.7%
  3.00x（上涨至 3 倍）-> -13.4%
  5.00x（上涨至 5 倍）-> -25.5%
  0.50x（下跌 50%）-> -5.7%（与上涨至 2 倍对称）
  0.20x（下跌 80%）-> -25.5%
```

**集中流动性（concentrated liquidity）IL（Uniswap v3）：**
- IL 按资本效率（capital efficiency）成比例放大（amplified）
- 对于区间（range）[p_lower, p_upper]，IL 乘数（multiplier）~ sqrt(p_upper/p_lower)
- 资本效率达到 10 倍的头寸，其 IL 约为 v2 头寸的 10 倍
- 若价格离开区间：头寸变为 100% 的单一资产（该方向上的最大 IL）

**IL 与手续费收入（fee income）的决策：**
```
净头寸损益（P&L）= fee_income - impermanent_loss - gas_costs

当以下条件成立时，LP 有利可图：
fee_income > IL + gas_costs

手续费收入取决于：
- 流经资金池（pool）的交易量（trading volume）
- 手续费档位（fee tier）（0.01% 至 1%）
- 你在活跃价格区间（active price range）内的流动性份额（share of liquidity）
- 头寸的存续时长（duration）
```

### 真实收益与排放收益（emission yield）

**排放收益（不可持续，unsustainable）：**
- 协议铸造（mint）新代币，并分配给 LP 与质押者（staker）
- 由通胀（inflation）而非收入资助——稀释现有持有者（holder）
- 典型生命周期：初始 APY 很高 -> 代币价格下跌 -> APY 下降 -> 总锁仓价值（total value locked，TVL）外流
- “流动性挖矿死亡螺旋（yield farming death spiral）”：卖出排放 -> 价格下跌 -> APY 下降 -> 更多卖出

**真实收益（可持续，sustainable）：**
- 产生自实际的协议收入（protocol revenue）（交易手续费（trading fee）、借款利息（borrowing interest）、清算费用（liquidation fee））
- 真实收益 = protocol_revenue_to_stakers / staked_value
- 真实收益较强的协议：GMX（30-40% 真实收益）、Gains Network、协议自有流动性（protocol-owned liquidity）模型
- 基准（benchmark）：若排放收益达到真实收益的 5 倍及以上，该代币很可能被高估（overvalued）

### 风险评估框架

**智能合约风险（smart contract risk）：**
- 审计（audit）状态：未经审计 = 极端风险，1 次审计 = 高风险，2 次及以上审计 + 漏洞赏金（bug bounty）= 中等风险
- 代码复杂度：可组合性（composability）层级会使风险成倍增加（收益聚合器 -> 借贷协议（lending protocol）-> AMM）
- 升级机制（upgrade mechanism）：不可变（immutable）合约更安全，但更难打补丁（patch）；代理模式（proxy pattern）会引入管理员密钥（admin key）风险
- 生产环境运行时间（time in production）：林迪效应（Lindy effect）——未发生漏洞利用（exploit）而存活 2 年以上的协议，风险更低

**市场风险（market risk）：**
- 价格发散（price divergence）带来的无常损失
- 稳定币（stablecoin）资金池的脱锚（depeg）风险
- 配对资产（paired asset）之间的相关性破裂（correlation breakdown）
- 黑天鹅（black swan）事件引发连环清算（cascading liquidation）

**流动性风险（liquidity risk）：**
- 你能否在没有显著滑点（slippage）的情况下退出头寸？
- 锁定期（lock-up period）与提款延迟（withdrawal delay）
- 协议 TVL 集中度（concentration）——若你超过资金池的 5%，退出冲击（exit impact）就是实质性的（material）
- 跨链（cross-chain）流动性挖矿的跨链桥风险（bridge risk）

**操作风险（operational risk）：**
- 预言机操纵（oracle manipulation）导致奖励计算出错
- 治理攻击（governance attack）改变奖励参数
- 前端被攻破（front-end compromise）（DNS 劫持（DNS hijack）、恶意合约授权（malicious contract approval））
- 链特有风险（chain-specific risk）（二层网络（L2）排序器停机（sequencer downtime）、跨链桥被攻击（bridge hack））

## 方法论

### 收益机会评估流程
1. **识别收益来源** — 它是真实收入、排放，还是二者的组合？
2. **计算真实 APY** — 计入复利频率（compounding frequency）、燃料费成本与 IL
3. **估计无常损失** — 对投资期限（investment horizon）内的预期价格变动建立模型
4. **评估风险** — 智能合约、市场、流动性与操作风险
5. **对回报进行风险调整** — 根据风险评估施加折减（haircut）
6. **比较替代方案** — 以简单的质押（staking）、借贷（lending）或持有（holding）作为比较基准
7. **适当确定规模** — 风险更高 = 配置更小；切勿集中于单一矿场（farm）

### IL 对冲策略
```
策略 1：Delta 中性（delta-neutral）LP
- 在 ETH/USDC 资金池中提供流动性
- 做空 ETH 永续合约（perpetual），其规模等于头寸价值的 50%
- IL 由永续合约的盈亏抵消（属于不完美对冲（imperfect hedge），但会降低方差（variance））
- 净回报 = 手续费收入 - 资金费率（funding rate）成本 - 残余 IL

策略 2：基于期权的对冲（options-based hedge）
- 买入该交易对中波动资产（volatile asset）的看跌期权（put option）
- 防范会放大 IL 的大幅下跌（downside move）
- 成本：期权权利金（option premium）会降低净收益（net yield）

策略 3：相关资产对挖矿（correlated pair farming）
- 对高度相关（high correlation）的资产对进行挖矿（stETH/ETH、WBTC/renBTC）
- 当价格同步变动时，IL 极小
- 收益更低，但风险低得多
```

### 仓位规模框架
```
风险层级（risk tier）配置：
- 蓝筹矿场（blue chip farm）（Aave、Uniswap 的主要交易对（major pair））：最高占 DeFi 配置的 30%
- 中等层级（mid-tier）（成熟协议（established protocol）、新的链）：最高 15%
- 高风险矿场（degen farm）（未经审计、高 APY、新协议）：最多 5%
- 任何单一矿场都不得超过总组合的 5%
- 每个头寸都已记录紧急退出计划
```

## 示例

### 示例 1：稳定币收益比较
```
策略 A — Curve 3pool LP：
- 来自手续费的基础 APY：2.5%
- CRV 排放：8%（按当前 CRV 价格计算）
- 总 APY：10.5%
- IL 风险：极小（全部都是稳定币）
- 智能合约风险：低（Curve 久经实战检验（battle-tested））
- 风险调整后收益（risk-adjusted yield）：约 9%

策略 B — Aave USDC 借贷：
- 供给 APY：3.5%
- 无 IL 风险
- 智能合约风险：低
- 风险调整后收益：约 3.2%

策略 C — 新协议稳定币矿场：
- 宣传 APY（advertised APY）：50%
- 由排放资助（该代币没有收入）
- 智能合约风险：高（未经审计，上线仅 2 周）
- 代币价格下跌之后的预期真实 APY：约 5-10%
- 风险调整后收益：约 2%（发生亏损的概率很高）

决策：策略 A 提供的风险调整后回报最好。
策略 C 的标题 APY（headline APY）具有误导性。
```

### 示例 2：ETH/USDC 集中流动性
```
Uniswap v3 ETH/USDC 头寸：
- ETH 价格：$2,000
- 区间：$1,700 - $2,300（±15%）
- 资本效率：相较全区间（full range）约为 6.7x
- 手续费档位：0.30%

情景分析（scenario analysis）（30 日期限）：
- 若 ETH 留在区间内：来自手续费的 APY 约为 25%
- 若 ETH 涨至 $2,500：头寸变为 100% USDC，IL = -8.2%（已被放大）
- 若 ETH 跌至 $1,500：头寸变为 100% ETH，IL = -11.3%（已被放大）

预期结果（历史波动率（historical volatility）= 80% 年化（annualized））：
- 留在区间内的概率：约 65%
- 预期手续费收入：在 $50,000 头寸上为 $1,200
- 预期 IL：-$400
- 净预期回报：$800 / $50,000 = 每月 1.6% = 约 19% APY

再平衡的燃料费成本：每次再平衡约 $80（每月 2-3 次）
扣除燃料费后的净收益：约 17% APY
```

### 示例 3：挖提卖（farm-and-dump）识别
```
已识别出的危险信号（red flag）：
- 协议 5 天前才上线，且没有审计
- APY：原生代币（native token）LP 为 2,000%
- 代币价格：较上线时下跌 60%
- TVL 在增长，但代币价格在下跌（人们一边挖矿一边卖出）
- 没有收入来源——100% 由排放资助
- 匿名团队（anonymous team），代码为分叉代码（forked code）

分析：
- 以美元计价的当前 APY：2000% * 0.4（代币下跌）= 约 800%
- 但代币每天约下跌 10%
- 每日收益：800% / 365 = 2.2%
- 每日代币跌幅：10%
- 每日净回报：-7.8%

结论：尽管标题 APY 很高，期望值仍为负（negative expected value）。
典型的挖提卖动态。避开。
```

## 质量门禁（quality gate）

在进入流动性挖矿头寸之前，请核实：

- [ ] 已识别 APY 来源——真实收益对比排放；可持续对比临时
- [ ] 已在计入复利、燃料费成本与无常损失之后，计算出真实 APY
- [ ] 已评估智能合约风险——审计、生产环境运行时间、代码复杂度、升级机制
- [ ] 已针对符合现实的价格情景对无常损失建立模型（而不仅仅是历史情景）
- [ ] 已按照风险层级确定头寸规模——切勿在高风险矿场中过度集中
- [ ] 已定义退出计划——什么情形会触发退出（IL 阈值（threshold）、APY 下降、安全隐患（security concern））？
- [ ] 已审阅代币排放时间表（emission schedule）——排放是否很快下降，从而使 APY 崩塌？
- [ ] 协议 TVL 趋势稳定或正在增长——TVL 下降可能表明聪明钱（smart money）正在退出
- [ ] 你占资金池的份额足够小，退出时不会造成显著的市场冲击（market impact）
- [ ] 入场、复利与退出的燃料费成本已经计入净回报计算
