# 仓位规模（position sizing）方法论

> 凯利（Kelly）准则、最优 f（optimal-f）、固定分数（fixed fractional）、波动率目标（volatility targeting）、风险平价仓位规模（risk parity position sizing），以及实务实施。

## 何时启用

- 用户正在为交易策略设计仓位规模规则
- 应用凯利准则或分数凯利（fractional Kelly）来确定下注规模
- 为系统化策略做基于波动率的仓位规模（volatility-based position sizing）
- 在各策略或各资产之间做风险预算（risk budgeting）与风险平价配置（risk parity allocation）
- 评估仓位规模、期望收益（expected return）与回撤（drawdown）风险之间的权衡
- 针对给定的策略概况（strategy profile），比较各种仓位规模方法

## 核心概念

### 凯利准则（Kelly criterion）

**原始凯利（二元结果，binary outcomes）**
- f* = (bp - q) / b，其中 b = 赔率（odds），p = 获胜概率，q = 1-p
- f* = 用于下注的资本比例
- 最大化长期几何增长率（geometric growth rate，即对数财富（log wealth））
- 示例：p = 0.55，b = 1（一赔一，even money）-> f* = (1*0.55 - 0.45)/1 = 0.10（下注资本的 10%）

**连续凯利（正态收益，normal returns）**
- f* = (mu - r_f) / sigma^2，其中 mu = 期望收益，sigma = 波动率
- 对于期望超额收益（excess return）为 15%、波动率为 20% 的策略：f* = 0.15/0.04 = 3.75x 杠杆（leverage）
- 这一杠杆水平使几何增长最大化
- 等价于在收益分布（return distribution）上最大化 E[ln(1 + f*r)]

**多资产凯利（multi-asset Kelly）**
- f* = Sigma^{-1} * mu（最优比例向量 = 协方差矩阵的逆乘以期望超额收益）
- 等价于风险厌恶（risk aversion）= 1 下的均值-方差优化（mean-variance optimization）（最大化对数效用（log utility））
- 需要估计期望收益与协方差矩阵（covariance matrix）——二者都含有噪声

### 全凯利（full Kelly）的实际问题

- 全凯利会产生极端回撤：出现 50% 回撤的概率大约为 50%
- 参数估计误差（parameter estimation error）：高估 mu 或低估 sigma 会导致过度加杠杆（overleveraging）
- 非正态收益（non-normal returns）：肥尾（fat tails）使全凯利更加危险
- 策略容量（strategy capacity）：全凯利可能意味着仓位超出市场流动性（market liquidity）
- 结果：专业交易者实际上几乎无人使用全凯利

### 分数凯利

- 使用 f = c * f_Kelly，其中 c 通常为 0.20 至 0.50（四分之一凯利至半凯利）
- 半凯利（half Kelly，c = 0.5）：增长率为全凯利增长率的 75%，但回撤大幅降低
- 四分之一凯利（quarter Kelly，c = 0.25）：增长率为全凯利增长率的 44%，但权益曲线（equity curve）非常平稳
- 分数凯利等价于带有混合估计的全凯利（与零收益先验（zero-return prior）相混合）
- 分数凯利对参数估计误差更为稳健（robust）

### 最优 f（Ralph Vince）

- 凯利准则面向非二元结果的推广
- f* = 在历史交易上使终值财富因子（terminal wealth factor, TWR）达到最大的那个比例
- TWR = 全部交易上 (1 + f * return_i / |worst_loss|) 的连乘积
- 以很小的步长把 f 从 0 测试到 1，用数值方法求出 f*
- 与凯利相关，但不假设某一分布——使用的是经验交易历史（empirical trade history）
- 危险之处：最优 f 是在样本内（in-sample）数据上计算的，可能过拟合（overfit）
- 与全凯利一样，会产生严重回撤；实务中应使用分数最优 f（fractional optimal-f）

## 方法论

### 固定分数仓位规模

1. 每笔交易承担资本的一个固定百分比（例如 1-2%）
2. 仓位规模 = (risk_per_trade * capital) / (entry - stop_loss)
3. 示例：$1M 资本，风险 1%，入场价 $50，止损价 $48
   - 风险金额 = $10,000
   - 仓位规模 = $10,000 / $2 = 5,000 股
4. 亏损之后自动缩小仓位，盈利之后自动放大仓位（反马丁格尔（anti-martingale））
5. 防止破产（ruin）：没有任何单笔交易的亏损能够超过该固定分数
6. 方法简单，并在系统化交易与主观交易（discretionary trading）中被广泛使用

### 基于波动率的仓位规模

**波动率目标**
1. 设定目标组合波动率（例如年化（annualized）10%）
2. 对每个仓位：weight_i = target_vol / (N * sigma_i)，其中 sigma_i 为该资产的波动率
3. 波动率更高的资产得到更小的仓位；波动率更低的资产得到更大的仓位
4. 当已实现波动率（realized volatility）显著偏离目标时，进行再平衡（rebalance）
5. 使每个仓位的风险贡献（risk contribution）相等（若彼此不相关）

**基于 ATR 的规模（海龟交易者（Turtle Traders））**
1. 对每个品种计算 N = 20 日 ATR（平均真实波幅（Average True Range））
2. 美元波动（dollar volatility）= N * point_value
3. 单位规模（unit size）= (权益的 1%) / dollar_volatility
4. 每个“单位”大约代表每日 1% 的权益（equity）风险
5. 每个市场的最大单位数：4（每个仓位承担的权益风险最多为 4%）
6. 每个相关组别（correlated group）的最大单位数：6-8

### 风险平价仓位规模

1. 目标是使每项资产或每个策略的风险贡献相等
2. 在简单（不相关）情形下：w_i 与 1/sigma_i 成比例
3. 存在相关性时：求解 w，使得对所有 i 都有 w_i * (Sigma * w)_i = RC_target
4. 资产 i 的风险贡献：RC_i = w_i * (Sigma * w)_i / (w' * Sigma * w)
5. 等风险贡献（equal risk contribution）：对所有 i，RC_i = 1/N
6. 低波动资产（债券，bonds）需要杠杆，才能与高波动资产（股票，equities）拉平
7. 桥水全天候（Bridgewater All Weather）是经典的风险平价组合

### 风险预算

1. 为每个策略或每个资产类别（asset class）分配风险预算（各预算不必相等）
2. 风险预算 = 归因于每个成分的总组合风险百分比
3. 示例：股票占全部风险的 40%，固定收益（fixed income）占 30%，另类资产（alternatives）占 30%
4. 求解能够实现目标风险配置（target risk allocation）的权重
5. 成分风险（component risk）= w_i * marginal_risk_i = w_i * (Sigma * w)_i / sigma_portfolio
6. 通过迭代，或使用优化，求出与目标风险预算相匹配的权重

### 含参数不确定性的凯利

**贝叶斯凯利（Bayesian Kelly）**
1. 不使用 mu 与 sigma 的点估计（point estimate），而使用后验分布（posterior distribution）
2. 最优下注规模要把参数不确定性（parameter uncertainty）计算在内
3. 得到的仓位小于代入式凯利（plug-in Kelly）——这是自然的收缩（shrinkage）
4. 在弥散先验（diffuse prior）下，贝叶斯凯利大约等于 0.5 * 代入式凯利

**收缩方法**
1. 将期望收益估计向零（或总均值（grand mean））收缩
2. 将协方差向结构化估计量（structured estimator，Ledoit-Wolf）收缩
3. 不确定性上升时，有效仓位规模随之下降
4. 相比朴素凯利（naive Kelly），它对估计误差更为稳健

## 示例

### 交易策略的凯利准则
```
策略回测：年化超额收益 = 12%，年化波动率 = 18%
全凯利：f* = 0.12 / 0.18^2 = 3.7x 杠杆
全凯利下的期望增长率：mu - 0.5*sigma^2*f = 12% - 0.5*3.24%*3.7 = 6%
全凯利下的期望最大回撤：大约 50%+

半凯利：f = 1.85x 杠杆
期望增长率：大约 4.5%
期望最大回撤：大约 25%

四分之一凯利：f = 0.93x 杠杆（无需杠杆）
期望增长率：大约 3%
期望最大回撤：大约 12%

建议：若回撤容忍度为 25%，采用半凯利（1.85x）；
若更为保守，采用四分之一凯利（0.93x）。
```

### 基于 ATR 的仓位规模
```
账户权益：$500,000
每单位风险：1% = $5,000

原油（CL）：ATR(20) = $2.50，点值 = $1,000/点
  美元波动 = $2.50 * $1,000 = $2,500
  单位规模 = $5,000 / $2,500 = 2 张合约

小型标普（E-mini S&P，ES）：ATR(20) = 45 点，点值 = $50/点
  美元波动 = 45 * $50 = $2,250
  单位规模 = $5,000 / $2,250 = 2 张合约（向下取整）

黄金（GC）：ATR(20) = $25，点值 = $100/点
  美元波动 = $25 * $100 = $2,500
  单位规模 = $5,000 / $2,500 = 2 张合约

每个仓位在每一个 ATR 波动上大约承担 $5,000（权益的 1%）风险。
每个市场最多 4 个单位 = 每个市场的权益风险为 4%。
```

### 风险平价配置
```
三资产组合：股票（波动率=16%）、债券（波动率=5%）、大宗商品（波动率=20%）
假设相关性为零（简化）：

等风险贡献目标：各 33.3%
w_equity 与 1/16 = 0.0625 成比例
w_bonds 与 1/5 = 0.2000 成比例
w_commod 与 1/20 = 0.0500 成比例

归一化：w_equity = 20%，w_bonds = 63%，w_commod = 16%
合计 = 99%（大约 1x 杠杆）

若目标组合波动率为 10%：
未加杠杆的组合波动率 = sqrt(0.20^2*16^2 + 0.63^2*5^2 + 0.16^2*20^2) = 5.4%
杠杆 = 10% / 5.4% = 1.85x
加杠杆后的权重：股票 37%，债券 117%，大宗商品 30%
```

## 质量关口（quality gate）

- 凯利比例必须用现实的收益估计来计算（扣除成本之后、扣除滑点（slippage）之后）
- 实务中切勿使用全凯利——对于估计良好的策略，建议的上限是半凯利
- 必须把参数不确定性考虑进去：使用贝叶斯凯利或分数凯利
- 仓位规模必须遵守市场流动性约束（占日均成交量（average daily volume, ADV）的最大百分比）
- 用于确定规模的波动率估计必须采用适当的回看期（lookback）（20-60 日已实现波动率，或指数加权移动平均（exponentially weighted moving average, EWMA））
- 当波动率估计或相关性估计发生实质性变化时，必须再平衡风险平价权重
- 无论凯利比例隐含的杠杆是多少，总组合杠杆都必须处于可接受的界限之内
- 规模规则必须在计入交易成本（transaction cost）与滑点的情况下进行回测
- 最大仓位规模限额必须作为硬约束（hard constraint）存在，并且独立于规模公式
- 记录规模方法论与各项参数；按季度复核
