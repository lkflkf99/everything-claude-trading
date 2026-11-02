# 期权希腊值（Greeks）管理

> 对冲 delta、gamma、vega、theta，并管理高阶希腊值（higher-order Greeks）。涵盖组合层面的风险管理、动态对冲（dynamic hedging）与再平衡（rebalancing）策略。

## 何时启用

- 用户管理期权组合，需要对冲或分析风险
- 构建或调整 delta 中性（delta-neutral）组合
- gamma 剥头皮（gamma scalping）策略，或 gamma 敞口分析
- 对波动率敏感头寸进行 vega 对冲（vega hedging）
- theta 衰减（theta decay）分析与时间衰减管理
- 针对奇异期权（exotic options）或大额头寸，使用高阶希腊值（vanna、volga、charm）
- 通过希腊值分解理解损益归因（P&L attribution）

## 核心概念

### 一阶希腊值（first-order Greeks）

**delta（d price / d spot）**
- 看涨期权（call）delta：0 到 +1；看跌期权（put）delta：-1 到 0
- 平值期权（ATM）的 delta 约为 +/-0.50（看涨期权因对数正态漂移（lognormal drift）而略高）
- delta 即对冲比率（hedge ratio）：每份看涨期权卖出 delta 股股票，即可达到 delta 中性
- 美元 delta（dollar delta）= delta * notional = 标的价格变动所对应的美元敞口
- delta 随现货（spot）（经由 gamma）、时间（经由 charm）和波动率（vol）（经由 vanna）而变化

**theta（d price / d time）**
- 衡量每日时间衰减——多头期权为负，空头期权为正
- 平值期权的 theta 最高（待损耗的时间价值最多）
- theta 是持有 gamma 的“成本”；theta 与 gamma 相互关联：在 Black-Scholes-Merton（BSM）下，theta approximately = -0.5 * gamma * S^2 * sigma^2
- 短期限平值期权的 theta 衰减最快
- 随着到期临近，theta 加速（看涨期权：theta = -S*sigma*phi(d1) / (2*sqrt(T))）

**vega（d price / d implied vol）**
- 对隐含波动率（implied volatility）变动的敏感度——多头期权为正
- 平值期权的 vega 最高
- vega 与 sqrt(T) 成正比：期限更长的期权 vega 更大
- vega 并非 BSM 意义上的真正希腊值（它不是模型参数），但对交易必不可少
- 加权 vega（weighted vega）：用 sqrt(T) 对 vega 归一化，以便跨期限比较

**rho（d price / d interest rate）**
- 对无风险利率（risk-free rate）的敏感度——短期限期权通常很小
- 对长期限期权和利率衍生品更为显著
- 看涨期权的 rho 为正；看跌期权的 rho 为负

### 二阶希腊值（second-order Greeks）

**gamma（d delta / d spot = d^2 price / d spot^2）**
- 衡量期权价格的凸性（convexity）——多头期权为正
- 平值、短期限期权的 gamma 最高
- 多头 gamma（long gamma）从大幅波动中获利（任一方向）；空头 gamma（short gamma）则亏损
- 美元 gamma（dollar gamma）= 0.5 * gamma * S^2 * (move%)^2 = 现货变动带来的损益
- gamma 与 theta 相互抵消：支付 theta 以持有 gamma（即 gamma-theta 权衡（gamma-theta tradeoff））

**vanna（d delta / d vol = d vega / d spot）**
- 交叉希腊值（cross-Greek）：波动率变化时 delta 如何变化，等价地，现货移动时 vega 如何变化
- 对风险逆转（risk reversal）与偏斜（skew）头寸至关重要
- 虚值看涨（OTM call）与实值看跌（ITM put）的 vanna 为正；虚值看跌（OTM put）与实值看涨（ITM call）的 vanna 为负
- 在偏斜环境中，vanna 敞口可以产生显著损益

**volga / vomma（d vega / d vol = d^2 price / d vol^2）**
- 期权价格相对于波动率的凸性
- 虚值期权与实值期权为正；平值期权约为零
- 解释了虚值期权的隐含波动率为何高于平值期权（波动率微笑（vol smile）是对 volga 的补偿）
- 对奇异期权的定价与对冲很重要（vanna-volga 方法（vanna-volga method））

**charm（d delta / d time）**
- delta 如何随时间流逝而变化
- 对于在不进行再平衡的情况下、随时间管理 delta 对冲至关重要
- 平值期权的 charm 较小；临近到期时，虚值与实值期权的 charm 可能显著

### 组合层面希腊值（portfolio-level Greeks）

- 组合 delta（portfolio delta）= 各头寸 delta 之和（线性加总）
- 组合 gamma（portfolio gamma）= 各头寸 gamma 之和（同一标的）
- 组合 vega（portfolio vega）= 各头寸 vega 之和
- 跨标的风险（cross-underlying risk）：组合风险需要相关性加权敞口（correlation-weighted exposure）
- 同一标的内希腊值可以相加；跨标的则需要因子模型（factor model）

## 方法论

### delta 对冲（delta hedging）

**离散 delta 对冲（discrete delta hedging）**
1. 计算组合 delta
2. 交易标的股票或期货以抵消 delta（delta 为空头则买入，delta 为多头则卖出）
3. 按选定频率再平衡：基于时间（time-based）（每日、每小时），或基于阈值（threshold-based）（当 delta 漂移达到 x）
4. 对冲误差（hedging error）：与 gamma * (actual_move^2 - implied_vol^2 * dt) 成正比
5. 经 delta 对冲后期权的损益 = 0.5 * gamma * S^2 * (realized_vol^2 - implied_vol^2) * dt 的路径积分（path integral）
6. 交易成本限制再平衡频率——最优频率在对冲误差与成本之间取得平衡

**期货对冲与现货对冲（futures vs. cash hedging）**
- 期货：资本效率高，无需融券（stock borrow），但存在展期风险（roll risk）和基差（basis）
- 现货（股票）：delta 精确匹配，无展期，但需要占用资本
- 外汇 delta 对冲（FX delta hedging）：视货币而定，使用即期、远期（forwards）或无本金交割远期（NDF）

### gamma 剥头皮

1. 建立多头 gamma 头寸（买入跨式（straddle）或宽跨式（strangle））
2. 连续进行 delta 对冲，或按间隔进行 delta 对冲
3. 每次对冲锁定已实现变动带来的利润：P&L = 0.5 * gamma * (dS)^2
4. 必须覆盖 theta 衰减：仅当已实现波动率（realized vol）高于隐含波动率时才盈利
5. 对已经 delta 对冲的头寸，盈亏平衡日度波动（breakeven daily move）= sqrt(2 * daily_theta / gamma)
6. 剥头皮频率很重要：过于频繁 = 交易成本高；过于稀疏 = 错过波动

### vega 对冲

1. 按行权价（strike）与到期日，计算波动率曲面（vol surface）上的组合 vega 敞口
2. 使用到期日匹配的期权（通常为平值）对冲 vega
3. vega 中性（vega-neutral）并不等于 volga 中性（volga-neutral）：二阶波动率风险仍然存在
4. 期限结构对冲（term structure hedging）：按到期日将 vega 分桶，并对每个桶分别对冲
5. 偏斜对冲（skew hedging）：使用风险逆转（买入虚值看跌、卖出虚值看涨），或叠加看跌/看涨价差（put/call spread）
6. 加权 vega 方法：将全部 vega 归一化到某一参考期限（例如 1 个月等值）

### 交叉希腊值对冲（cross-Greek hedging）

同时构造 delta-gamma-vega 中性（delta-gamma-vega neutral）：
1. 要中性化的希腊值有多少个，至少就需要多少个对冲工具
2. delta 中性：使用标的（1 个工具）
3. delta-gamma 中性（delta-gamma neutral）：使用标的，加上同一到期日的 1 个期权（2 个工具）
4. delta-gamma-vega 中性：使用标的，加上不同行权价或到期日的 2 个期权（3 个工具）
5. 求解线性方程组，得到对冲比率
6. 过度对冲（over-hedging）会引入其他风险——按重要性对希腊值排列优先顺序

### 再平衡决策

- **基于时间（time-based）**：不论行情是否变动，每小时或每日都进行对冲——简单，但可能产生不必要的交易
- **基于变动（move-based）**：当 delta 超过阈值时对冲——高效，但可能错过快速行情
- **容忍带（tolerance bands）**：为每个希腊值设定可接受区间；任一希腊值突破区间即再平衡
- **基于效用（utility-based）**：综合考虑风险厌恶、交易成本与预期持有期，优化再平衡

## 示例

### delta-gamma 对冲构建
```
头寸：做空股票 XYZ 的 1000 份看涨期权，K=100，T=3M
看涨期权 delta = 0.55，gamma = 0.03，vega = 0.25

当前敞口：
  组合 delta = -1000 * 0.55 = -550
  组合 gamma = -1000 * 0.03 = -30
  组合 vega = -1000 * 0.25 = -250

用标的加不同行权价的看涨期权对冲（K=110，delta=0.35，gamma=0.02）：
  gamma 对冲：买入 30/0.02 = 1500 份 K=110 的看涨期权
  gamma 对冲后的净 delta：-550 + 1500*0.35 = -550 + 525 = -25
  买入 25 股以抹平 delta。
  净 vega：-250 + 1500*0.20 = +50（残余 vega——需要第三个工具才能归零）
```

### gamma 剥头皮损益
```
多头跨式：价格为 $100 的股票上，平值看涨 + 平值看跌。
跨式 gamma = 0.04，每日 theta = -$200。
第 1 日：股票由 $100 变动至 $103。delta 对冲：在 $103 卖出 0.04*3*100 = 12 股。
第 2 日：股票由 $103 变动至 $99。买回股票，并额外卖出。
每日 gamma 损益 = 0.5 * 0.04 * 100^2 * (actual_move/100)^2 * 100 份合约。
若股票每日变动 $3（每日已实现波动率 3%），gamma 损益 = 0.5*0.04*9*100 = $180/日。
净损益 = $180 - $200 theta = -$20/日。每日波动需 >$3.16 才能盈亏平衡。
```

## 质量门槛（quality gate）

- 组合希腊值必须通过完整重新定价的扰动重估（bump-and-revalue）计算，而不能只依赖解析形式的 BSM
- 扰动量：delta（现货 1%），gamma（由两次 delta 计算得到），vega（1 个波动率点），theta（1 天）
- 偏斜敞口显著的组合必须计算交叉希腊值（vanna、volga）
- 对冲误差跟踪：每日比较实际损益与希腊值预测损益（Greek-predicted P&L）
- 任何 gamma 剥头皮或 delta 对冲分析都必须计入再平衡成本
- 希腊值必须正确汇总：同一标的直接相加，跨资产使用因子模型
- 必须监控临近到期、行权价接近平值的头寸的钉住风险（pin risk）
- 必须对希腊值进行压力测试：在现货 +-20% 与波动率 +-5 个点的冲击下计算希腊值
- 报告以美元计价的希腊值（美元 delta、美元 gamma、美元 vega（dollar vega）），供跨组合比较
