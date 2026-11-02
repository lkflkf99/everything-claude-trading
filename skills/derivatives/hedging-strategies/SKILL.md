# 衍生品对冲（hedge）策略

name: hedging-strategies
description: 衍生品对冲——delta 中性（delta-neutral）、gamma 剥头皮（gamma scalping）、vega 对冲（vega hedging）。
origin: ECT

## 何时启用

- 用户希望对冲衍生品头寸（position）或投资组合（portfolio）
- 设计带有 gamma 剥头皮的 delta 中性策略
- 在波动率曲面（vol surface）上管理 vega 敞口（exposure）
- 使用期权或期货（futures）构建组合对冲
- 分析交叉对冲（cross-hedging）与基差风险（basis risk）
- 理解套期会计（hedge accounting）要求

## 首要问题

1. 需要被对冲的头寸是什么（单只期权、交易账簿（book）、投资组合）？
2. 主要关注哪些希腊值（Greeks：delta、gamma、vega、rho、theta）？
3. 对冲目标是什么（最小化方差（variance）、保护下行（downside）、降低尾部风险（tail risk））？
4. 再平衡（rebalancing）频率与交易成本（transaction cost）预算是多少？
5. 对冲设计是否存在会计或监管约束？

## 核心概念

### Delta 对冲

Delta 对冲抵消期权头寸对标的（underlying）变动的一阶敏感度（first-order sensitivity）。

```
基本 delta 对冲：
  期权头寸：做多（long）N 张看涨期权（calls），delta = 0.55
  对冲：做空（short）标的 N * 0.55 股
  净 delta = N * 0.55 - N * 0.55 = 0（delta 中性）

  delta 随标的移动而变化（gamma），因此必须对对冲进行再平衡

离散 delta 对冲：
  - 实践中无法做到连续对冲（continuous hedging）
  - 按固定间隔（每日、每小时）再平衡，或在 delta 达到阈值时再平衡
  - 对冲误差（hedging error）= gamma、已实现波动率（realized vol）与再平衡频率的函数

  每次再平衡的对冲误差：
    epsilon ~ 0.5 * Gamma * (delta_S)^2 - Theta * delta_t
    这就是 gamma-theta 权衡（gamma-theta tradeoff）：gamma 利润抵消 theta 衰减

Delta 对冲盈亏（P&L）：
  对于已做 delta 对冲的多头期权头寸：
    每日盈亏 = 0.5 * Gamma * S^2 * (realized_return^2 - implied_vol^2 * dt)
    若已实现波动率 > 隐含波动率（implied vol）：盈利（买入了便宜的波动率）
    若已实现波动率 < 隐含波动率：亏损（买入了昂贵的波动率）
```

### Gamma 剥头皮

Gamma 剥头皮是对已做 delta 对冲的期权头寸进行主动管理，用以捕捉已实现波动率与隐含波动率之差。

```
机制：
  1. 买入期权（多头 gamma（long gamma）头寸）
  2. 用标的做 delta 对冲
  3. 标的上涨时：delta 上升，卖出股票重新对冲（rehedge），即卖在高位
  4. 标的下跌时：delta 下降，买入股票重新对冲，即买在低位
  5. 净效果：系统性地低买高卖

盈亏分解：
  Gamma 剥头皮盈亏 = Gamma 盈亏 - Theta 成本

  Gamma 盈亏（每日）：
    = 0.5 * Gamma * S^2 * (daily_return^2)
    = 0.5 * Gamma * S^2 * realized_vol^2 * dt

  Theta 成本（每日）：
    = -Theta（期权时间衰减（time decay））
    = 0.5 * Gamma * S^2 * implied_vol^2 * dt（近似，适用于平值（ATM）期权）

  每日净盈亏：
    = 0.5 * Gamma * S^2 * (realized_vol^2 - implied_vol^2) * dt

  盈亏平衡（breakeven）：已实现波动率 = 隐含波动率
  盈利条件：已实现波动率 > 隐含波动率（买入了便宜的期权）
  亏损条件：已实现波动率 < 隐含波动率（买入了昂贵的期权）

最优再平衡频率：
  过于频繁：交易成本吃掉 gamma 利润
  过于稀疏：delta 漂移（delta drift）过大，gamma 捕捉不足
  经验法则：当 delta 变动达到 0.05-0.10 时再平衡
  或采用按 gamma * 预期变动校准后的固定间隔
  Zakamouline (2006)：最优带宽（optimal bandwidth）= f(gamma, transaction_cost, vol)
```

### Vega 对冲

Vega 对冲抵消对隐含波动率变动的敏感度。

```
为何对冲 vega：
  - 期权账簿会累积大量 vega 敞口
  - 波动率曲面的移动可造成显著的盈亏波动
  - vega 风险无法用标的对冲（只能用其他期权对冲）

Vega 对冲方法：

  1. 单行权价（strike）vega 对冲：
     用另一只期权上的相反头寸抵消 vega
     示例：做多 3 个月平值看涨（vega = 0.15）
     对冲：做空 3 个月平值看跌期权（puts）；vega 相同，delta 不同——须调整 delta
     局限：仅对冲该行权价/期限（tenor）上的平行波动率平移（parallel shift）

  2. 跨期限结构（term structure）的 vega 加权对冲：
     短期期权的单位波动率 vega 较低
     长期期权的 vega 较高
     在各期限分桶（tenor buckets）上匹配加权 vega：1M、3M、6M、1Y、2Y
     残余：波动率曲线扭转（twist）与蝶式（butterfly）敞口

  3. Vanna 与 volga 对冲：
     Vanna = d(delta)/d(vol) = d(vega)/d(spot)
     Volga = d(vega)/d(vol)（二阶波动率敏感度）
     对于奇异期权（exotic options）：用 25-delta 风险逆转（risk reversals）和宽跨式（strangles）对冲 vanna 与 volga
     这是外汇（FX）奇异期权交易台的标准做法

Vega 分桶：
  将总 vega 分解到各期限分桶：
    1M vega：对 1 个月隐含波动率变动的敏感度
    3M vega：对 3 个月隐含波动率变动的敏感度
    6M vega：对 6 个月隐含波动率变动的敏感度
    1Y vega：对 1 年隐含波动率变动的敏感度
  对每个分桶独立对冲
  监控残余曲线风险（波动率期限结构的平坦化（flattening）与陡峭化（steepening））
```

### 用期权进行组合对冲

```
用指数期权对冲股票组合：

  组合 beta 方法：
    组合价值：$10M，相对 S&P 500 的 beta = 1.2
    SPX 位于 5000，合约乘数（contract multiplier）= 100
    需要对冲的名义金额（notional）：$10M * 1.2 = $12M
    所需合约数：$12M / (5000 * 100) = 24 张看跌期权

  保护性看跌期权（protective put）：
    买入 24 张行权价为 95% 的 SPX 看跌（虚值（OTM）5%）
    成本：约为组合价值的 2%（年化（annualized），取决于波动率）
    保护效果：将亏损限制在约 7%（5% 免赔额（deductible）+ 看跌成本）

  领式（collar）：
    买入 95% 看跌 + 卖出 105% 看涨（零成本（zero-cost）或接近零成本）
    将上行（upside）封顶在 +5%，但消除低于 -5% 的下行
    常用于集中持股头寸与税务递延对冲（tax-deferred hedging）

  看跌价差（put spread）：
    买入 95% 看跌 + 卖出 85% 看跌（成本降低 40-60%）
    在 -5% 与 -15% 之间提供保护
    超过 -15% 不再提供保护（崩盘中的跳空风险（gap risk））

降低成本的技术：
  - 看跌价差：卖出更低行权价的看跌，以降低权利金（premium）
  - 领式：卖出上行看涨，为看跌融资
  - 看跌比例价差（put ratio spread）：买入 1 张平值看跌，卖出 2 张虚值看跌（风险：跌破较低行权价）
  - 日历价差（calendar spread）：卖出短期看跌，买入长期看跌
  - 海鸥式（seagull）：看跌价差 + 卖出虚值看涨
```

### 交叉对冲与基差风险

```
交叉对冲：
  用相关但并不相同的工具对冲某一敞口
  示例：用行业 ETF（sector ETF）对冲单只股票，用相关品种对冲大宗商品（commodity）

基差风险：
  基差（basis）= 被对冲资产的现货价格（spot）- 对冲工具的价格
  基差风险 = 对冲期限（hedge horizon）内基差的变异程度

  基差风险的来源：
    - 品级/品质差异（Brent 相对 WTI）
    - 地点差异（Henry Hub 相对 TTF 天然气）
    - 时间差异（对冲到期日相对敞口到期日）
    - 跨资产相关性（correlation）不稳定

最优对冲比率（optimal hedge ratio）（最小方差（minimum variance））：
  h* = rho * (sigma_hedged / sigma_hedge_instrument)
  其中 rho = 被对冲资产与对冲工具之间的相关性
  若 rho = 0.8，sigma_hedged = 20%，sigma_hedge = 25%：
    h* = 0.8 * (20/25) = 0.64
    对冲名义金额的 64%，而不是 100%

  对冲有效性（hedge effectiveness）：
    R^2 = rho^2 = 被消除方差所占的比例
    当 rho = 0.8：对冲有效性 = 64%（残余风险（residual risk）显著）
    当 rho = 0.95：对冲有效性 = 90%（对冲效果较好）

交叉对冲示例：
  股票相对 ETF：相关性高（大盘股（large caps）相对行业 ETF 为 0.85-0.95）
  商品品级：中等（Brent 相对 WTI 为 0.80-0.95）
  外汇代理对冲（proxy hedge）：相关性强弱不一（0.5-0.9，取决于货币对之间的关系）
```

### 套期会计

```
IAS 39 / IFRS 9 / ASC 815 的要求：

  公允价值套期（fair value hedge）：
    - 对冲已确认资产或负债的公允价值变动
    - 套期工具（hedging instrument）与被套期项目（hedged item）均通过盈亏进行盯市（marked to market）
    - 若套期有效，可降低盈亏波动

  现金流量套期（cash flow hedge）：
    - 对冲未来现金流量的变动性
    - 套期利得或损失的有效部分计入其他综合收益（OCI, Other Comprehensive Income）
    - 当被套期现金流量影响盈余（earnings）时，转入盈亏
    - 无效部分直接计入盈亏

  套期有效性要求：
    - 前瞻性（prospective）：证明套期将会高度有效（highly effective）（IAS 39 下为 80-125%）
    - IFRS 9：不再设置 80-125% 的明线（bright-line）测试，但要求存在经济关系（economic relationship）
    - 回顾性（retrospective）：每个期间检验实际有效性
    - 文档：在起始时（inception）作出正式指定（designation）

  关键条款匹配（critical terms match）：
    - 名义金额、到期日、标的、重置日（reset dates）应当匹配
    - 完全匹配：套期会计的处理较为直接
    - 不完全匹配：必须论证并计量有效性

  对交易决策的影响：
    - 套期会计约束可能妨碍最优对冲设计
    - 滚动短期对冲相对单一长期对冲：会计影响并不相同
    - 基差风险可能导致套期无效（ineffectiveness），从而不再符合套期会计的适用资格
```

## 详细方法

### 交易账簿的希腊值管理

```
多维风险管理：

  第 1 步：按标的、期限、行权价分桶（strike bucket）计算汇总希腊值
    - 按标的列示 delta（已轧差（netted））
    - 按标的与期限列示 gamma
    - 按标的、期限与行权价列示 vega（波动率曲面网格）
    - theta（投资组合的总时间衰减）

  第 2 步：按各项希腊值设定风险限额
    Delta：每个标的的 |delta| 上限 = $X（或等价股数）
    Gamma：标的每变动 1%，|gamma| 上限 = $Y
    Vega：每个期限分桶、每 1 个波动率点（vol point），|vega| 上限 = $Z
    Theta：监控每日盈亏流失（P&L bleed），确保 gamma 剥头皮能够将其抵消

  第 3 步：对冲优先级
    1. Delta：最先对冲（最大且最即时的风险）
    2. Gamma：通过期权交易来管理（买入或卖出期权）
    3. Vega：用期限匹配的期权或方差互换（variance swaps）对冲
    4. 交叉希腊值（cross-Greeks：vanna、volga）：持续监控，若影响重大则对冲

  第 4 步：残余风险报告
    报告未对冲敞口：钉住风险（pin risk）、相关性、跳空风险
    压力测试（stress test）：出现 3-sigma 变动并叠加波动率飙升（vol spike）时会怎样
```

### 动态对冲成本分析

```
Delta 对冲的成本（Leland 1985）：
  计入对冲成本的修正波动率：
    sigma_adjusted = sigma * sqrt(1 + sqrt(2/pi) * k / (sigma * sqrt(dt)))
  其中 k = 往返交易成本（round-trip transaction cost），dt = 再平衡间隔

  当 sigma = 20%、k = 0.1%、按日再平衡时：
    sigma_adjusted = 20% * sqrt(1 + 0.30) = 22.8%
    对冲成本使有效隐含波动率增加约 2.8 个波动率点

  含义：期权按 20 的隐含波动率卖出，但对冲成本相当于 22.8 的波动率
  必须以高于已实现波动率与对冲成本之和的隐含波动率卖出期权，才能获得盈利

成本优化：
  1. 加宽再平衡带宽：降低成本，但增大跟踪误差（tracking error）
  2. 改用期权而非标的进行对冲：降低再平衡频率
  3. 组合轧差（netting）：对冲之前，先在相关头寸之间抵消 delta
  4. 批量对冲（batch hedging）：汇总 delta 变动，每日执行一次
```

## 质量门槛

在实施对冲策略之前：

- [ ] 被对冲的风险已清楚识别（delta、gamma、vega、尾部，或全部）
- [ ] 已选用基差风险最小的对冲工具
- [ ] 已用适当方法计算对冲比率（最小方差、经 beta 调整（beta-adjusted））
- [ ] 已量化对冲的交易成本（再平衡成本会侵蚀表现）
- [ ] 已确定再平衡频率（权衡（tradeoff）：跟踪误差与成本）
- [ ] 已计量并接受交叉对冲的基差风险
- [ ] 压力测试：对冲在 2008、2020 情景中的表现
- [ ] 已检查套期会计要求（如适用）
- [ ] 已核实对冲工具的流动性（压力之下能否展期（roll）并调整？）
- [ ] 对冲之后的残余风险已记录，并向风险管理报告
