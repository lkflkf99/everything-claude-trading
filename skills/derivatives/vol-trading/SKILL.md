# 波动率交易（volatility trading）

name: vol-trading
description: 波动率交易——跨式（straddle）、方差互换（variance swap）、离散度（dispersion）、VIX。
origin: ECT

## 何时启用

- 用户希望把波动率作为一类资产（asset class）来交易
- 分析已实现波动率（realized volatility，RV）与隐含波动率（implied volatility，IV），以及波动率风险溢价（variance risk premium，VRP）
- 为方差互换与波动率互换（vol swap）定价或交易
- 设计离散度交易（指数波动率相对个股波动率（single-stock vol））
- 交易 VIX 期货（futures）、期权（options），或与 VIX 相关的产品
- 构建带尾部保护（tail protection）的系统化卖出波动率（systematic vol selling）策略

## 首要问题

1. 你是在做方向性波动率交易（directional：做多/做空（long/short）波动率），还是相对价值（relative value：期限结构（term structure）、偏斜（skew））？
2. 标的（underlying）是什么（个股（single stock）、股票指数（equity index）、外汇（FX）、利率（rates））？
3. 目标持有期（holding period）是多长（日内（intraday）、数日、数周、数月）？
4. 对尾部事件（tail event）的风险承受度（risk tolerance）如何（波动率策略具有极端尾部（extreme tails））？
5. 这是系统化（systematic）策略，还是主观（discretionary）波动率策略？

## 核心概念

### 已实现波动率与隐含波动率

```
已实现波动率（RV）：
  由过去收益率衡量的历史波动率（historical volatility）
  收盘到收盘（close-to-close）：sigma = sqrt(252 * (1/N) * sum((r_t - r_bar)^2))
  高低价（high-low，Parkinson）：利用日内波幅（intraday range）的更有效估计量（estimator）
  Yang-Zhang：结合开盘-收盘（open-close）与最高-最低，得到不依赖漂移（drift）的估计

隐含波动率（IV）：
  市场对未来波动率的预期，从期权价格中提取
  依赖模型：通常为 Black-Scholes 隐含波动率
  表示使模型价格等于市场价格的那一个波动率

关键关系：
  IV - RV = 波动率风险溢价（VRP）
  VRP 平均为正：期权系统性“偏贵”
  SPX 的 VRP：约 3-5 个波动率点（vol points）（IV 约 18%，RV 长期平均约 15%）
  VRP 所补偿的风险：跳跃风险（jump risk）、波动率的波动率风险（volatility-of-volatility risk）、崩盘风险（crash risk）

度量 VRP：
  VRP_realized = IV(t-30) - RV(t-30, t)   （事后（ex-post））
  对 SPX 而言，约 80% 的月份 VRP 为正
  VRP 在短期限期权（近月（front month））上最大
  VRP 在持续的低波动率状态（low-vol regime）（2017）中收窄，并在危机（2008、2020）中反转（invert）
```

### 方差互换

方差互换提供对已实现方差（realized variance）的纯粹敞口（exposure），无需管理 delta 或 gamma。

```
机制：
  到期时，收益（payoff）= Notional_variance * (Realized_Variance - Strike_Variance)

  Notional_variance = Vega_notional / (2 * K_vol)
  其中 K_vol = 以波动率表示的行权价（strike）

  公允行权价（fair strike，K_var）：
    K_var = (2/T) * integral[exp(rT) * (OTM_put_price/K^2 + OTM_call_price/K^2) dK]
    这就是 VIX^2 公式：方差互换行权价 = 风险中性（risk-neutral）期望方差
    需要虚值（OTM）期权价格的连续统（continuum）（实践中通过插值（interpolation）得到）

  方差互换与波动率互换：
    方差互换：收益对方差线性（sigma^2）
    波动率互换：收益对波动率线性（sigma）——更难复制（replicate）
    凸性调整（convexity adjustment）：K_vol_swap < K_var_swap（詹森不等式（Jensen's inequality））
    方差互换的行权价始终高于波动率互换

盈亏（P&L）示例：
  行权价：20% 波动率（400 个方差点（variance points））
  已实现波动率：25%（625 个方差点）
  Vega 名义金额（vega notional）：$100,000
  方差名义金额（variance notional）：$100,000 / (2 * 20) = 每个方差点 $2,500
  盈亏 = $2,500 * (625 - 400) = $562,500

关键特征：
  - 无需 delta 对冲（delta hedge）（纯粹的波动率敞口）
  - 盯市（mark-to-market）：对剩余隐含波动率与截至目前的已实现波动率两者都敏感
  - 凸性（convexity）：方差互换的收益对波动率呈凸性（受益于波动率飙升（vol spike））
  - 尾部风险（tail risk）：做空方差的下行（downside）没有上限（已实现波动率可飙升至 80%+）
```

### VIX 期货与期权

```
VIX 指数（index）：
  VIX = sqrt((2/T) * sum(delta_K/K_i^2 * e^(rT) * Q(K_i)) * 100^2)
  其中 Q(K_i) = SPX 上的虚值期权价格
  VIX 衡量 SPX 的 30 日期望方差（年化（annualized），以波动率表示）
  VIX 不能直接交易（它是一个计算结果，不是证券（security））

VIX 期货：
  VIX 期货在到期时收敛至 VIX
  期限结构：通常处于升水（contango）（远月（longer-dated）> 近月（shorter-dated））
    正常升水：每月约 5%（VIX = 15，次月（2nd month）= 16.5）
    贴水（backwardation）：出现在波动率飙升期间（VIX = 35，次月 = 30）

  展期收益（roll yield）：
    升水时：做多 VIX 期货每月流失约 5%（负展期收益）
    贴水时：做多 VIX 期货从展期中获得收益（正展期收益）
    这就是为何做多 VIX 的交易所交易产品（ETP）（VXX、UVXY）在平静市场中每年亏损约 60-80%

VIX 期权：
  期权标的是 VIX 期货（不是 VIX 现货（spot））
  VIX 看涨期权（calls）：常被用作尾部对冲（tail hedge）（组合保险（portfolio insurance））
  VIX 看跌期权（puts）：卖出以收割（harvest）VRP（若波动率飙升则风险很高）
  VIX 期权有自己的波动率曲面（vol surface）（波动率的波动率（vol-of-vol））
  VIX 看涨偏斜极为陡峭（上行（upside）看涨非常昂贵）

交易 VIX 期限结构：
  日历价差（calendar spread）：做多近月、做空远月（back month）（或相反）
  论点（thesis）：期限结构将变平（flatten）（做多近月）或变陡（steepen）（做空近月）
  持有收益（carry）：取决于升水/贴水的斜率
  风险：近月 VIX 极度波动（一天内可以变动 30-50%）
```

### 离散度交易

离散度交易利用指数隐含波动率与指数成分股（constituent）隐含波动率之间的差异。

```
概念：
  指数方差 = 个股方差的加权平均 + 协方差（covariance）项
  sigma_index^2 = sum(w_i^2 * sigma_i^2) + sum_i_neq_j(w_i * w_j * sigma_i * sigma_j * rho_ij)

  若隐含相关性（implied correlation）“过高”：
    卖出指数跨式（或方差互换）
    买入个股跨式（或方差互换）
    利润 = 卖出的指数波动率 - 按 vega 加权（vega-weighted）买入的个股波动率

  指数波动率通常偏贵（rich）的原因：
    - 指数期权需求很高（组合对冲（portfolio hedging））
    - 这会把指数隐含波动率相对成分股波动率抬高
    - 大多数时候，隐含相关性 > 已实现相关性（realized correlation）

离散度交易盈亏：
  盈亏 = (implied_correlation - realized_correlation) * correlation_vega
  大多数时候为正（隐含相关性 > 已实现相关性）
  危机中为负（相关性飙升至 0.7-0.9，离散度出现亏损）

实施方式：
  卖出指数方差互换，买入前 20-50 只成分股的方差互换
  按 vega 加权，使入场时达到相关性中性（correlation-neutral）
  或者：卖出指数跨式，买入成分股跨式（全部做 delta 对冲）
  风险：相关性飙升（2008：已实现相关性达到 0.8，离散度大幅亏损）

典型盈亏轮廓：
  胜率（win rate）：约 70-75% 的月份
  平均盈利：名义金额（notional）的 0.3-0.5%
  平均亏损：名义金额的 1-3%
  夏普比率（Sharpe）：0.4-0.8（尾部事件之前）
  最大亏损：危机中为名义金额的 5-15%（必须据此确定仓位（size））
```

### 带尾部保护的系统化卖出波动率

```
核心策略：系统化收割波动率风险溢价

  裸卖波动率（naked vol selling）（无保护）：
    卖出 30 日 SPX 跨式或宽跨式（strangle），并做 delta 对冲
    期望收益（expected return）：VRP * 敞口（适度仓位（modest sizing）下年化约 3-5%）
    风险：理论上没有上限，实践中为 -30% 至 -50%（2008、2018 年 Volmageddon（波动率末日））
    夏普比率：0.5-0.8，但具有极端负偏度（negative skew）（-3 到 -5）

  带尾部保护的卖出波动率方法：

  1. 买入虚值看跌（put spread collar）：
     卖出平值（ATM）跨式，买入虚值 10-15% 的看跌
     保护成本：每月为名义金额的 1-2%
     使收割到的 VRP 减少 30-50%，但为最大亏损封顶
     净夏普比率：0.3-0.5，偏度好得多

  2. VIX 看涨对冲：
     卖出 SPX 看跌（做空波动率），买入 VIX 看涨（尾部对冲）
     VIX 看涨很贵，但凸性很高
     使用 20-30 delta 的 VIX 看涨，期限在 2-3 个月之后
     对冲比率（hedge ratio）：把收到权利金（premium）的 10-20% 花在 VIX 看涨上

  3. 有管理的卖出波动率（条件式（conditional））：
     仅当 VRP 高于阈值（threshold）时卖出波动率（例如 IV - RV > 3 个波动率点）
     当 VIX 期限结构反转时减仓或退出（贴水 = 压力信号（stress signal））
     止损（stop loss）：若组合在一个月内下跌超过 X%，退出全部空头波动率
     相对无条件卖出（unconditional selling），夏普比率改善至 0.6-1.0

  4. 带上限的方差互换：
     卖出封顶方差互换（capped variance swap）（最大赔付（payout）封顶在行权价的 2.5 倍）
     属于标准的交易所交易产品（在部分交易所上市）
     上限明确限制尾部风险
     行权价略低于未封顶（uncapped）合约（作为上限的补偿）

  5. 风险逆转叠加（risk reversal overlay）：
     卖出虚值看跌（卖出波动率），买入更虚值的看跌（尾部保护）
     净头寸：看跌价差（put spread），不是裸空（naked short）
     在风险有界（bounded risk）的前提下，收取裸卖看跌权利金的约 60-70%
```

## 详细方法

### 波动率曲面相对价值

```
偏斜交易：
  风险逆转（risk reversal）：卖出 25-delta 看涨，买入 25-delta 看跌（或相反）
  蝶式（butterfly）：买入 25-delta 看涨 + 买入 25-delta 看跌，卖出 2x 平值
  论点：相对公允价值（fair value），偏斜过陡或过平

期限结构交易：
  日历价差：卖出近月波动率，买入远月波动率（或相反）
  论点：期限结构的形态将发生变化
  持有收益：近月波动率衰减更快（单位 vega 的 theta 更高）

  指标：
    偏斜贵贱（skew richness）：当前 25d 偏斜相对历史分位数（historical percentile）
    期限结构斜率：3M - 1M 隐含波动率相对历史水平
    波动率的波动率：VVIX 水平相对 VIX（状态指标（regime indicator））
```

### 波动率头寸的仓位确定

```
关键原则：按尾部情景确定仓位，而不是按平均情景

  方差互换名义金额：
    最大亏损情景：已实现波动率 = 80%（危机），行权价 = 20%
    盈亏 = vega_notional / (2 * 20) * (6400 - 400) = vega * 150
    若可接受的最大亏损 = $1M：vega_notional = $1M / 150 = $6,667

  跨式/宽跨式头寸：
    计算压力情景下的最大亏损（例如价格变动 -20%，同时波动率处于 60%）
    确定仓位，使压力亏损 < 风险限额（risk limit）（通常为资产净值（NAV）的 2-5%）

  做空波动率的经验法则（rule of thumb）：
    最多把组合资产净值的 3-5% 配置为潜在亏损
    这会显著限制做空波动率的名义敞口
    Volmageddon（2018 年 2 月）：XIV 在一天内亏损 96%
```

## 质量门槛

在部署波动率交易策略之前：

- [ ] VRP 度量正确（在相关区间上比较 IV 与 RV）
- [ ] 尾部风险已量化：已对最大历史亏损建模（2008、2018、2020）
- [ ] 仓位按尾部情景确定，而不是按平均情景
- [ ] 若卖出波动率，尾部对冲已就位（虚值看跌、VIX 看涨，或封顶方差）
- [ ] 希腊值（Greeks）已管理：已估计 delta 对冲的频率与成本
- [ ] 已计算 VIX 期货策略的展期成本（roll cost）（升水流失（contango bleed））
- [ ] 已对离散度的相关性风险做压力测试（危机相关性 = 0.8+）
- [ ] 已对压力下的保证金（margin）要求建模（波动率飙升时交易所会提高保证金）
- [ ] 已定义紧急停止开关（kill switch）：回撤（drawdown）、VIX 水平或期限结构反转（inversion）的退出触发条件
- [ ] 盈亏归因（P&L attribution）分开列示：VRP 收割、gamma 剥头皮（gamma scalping）、theta 衰减（theta decay），以及盯市
