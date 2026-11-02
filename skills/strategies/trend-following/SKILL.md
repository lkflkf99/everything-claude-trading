# 趋势跟踪（trend following）

name: trend-following
description: 趋势跟踪策略——商品交易顾问（CTA）风格、移动平均线（moving averages）、突破系统（breakout systems）、海龟交易（Turtle Trading）。在设计基于趋势的系统时使用。

## 何时启用

- 用户希望构建系统化的趋势跟踪或 CTA 风格策略
- 设计均线交叉（moving-average crossover）或通道突破（channel breakout）系统
- 实施海龟交易规则或类似的机械系统（mechanical systems）
- 使用平均真实波幅（Average True Range, ATR）或基于波动率（volatility）的方法进行仓位规模（position sizing）
- 在期货市场中构建多资产（multi-asset）趋势组合

## 首先要问的问题

1. 市场与工具（instruments）是什么（管理期货（managed futures）、股票（equities）、外汇（FX）、加密货币（crypto））？
2. 趋势如何定义——移动平均线、突破（breakouts），还是动量（momentum）？
3. 趋势的时间跨度（time horizon）是什么——短期（数日）、中期（数周），还是长期（数月）？
4. 这是单一工具系统，还是分散化的多市场组合（diversified multi-market portfolio）？
5. 风险预算（risk budget）与可接受的最大回撤（maximum acceptable drawdown）是多少？

## 核心概念

### 趋势跟踪为何有效

趋势跟踪利用的是资产价格中的序列相关（serial correlation）。它之所以有效，是因为：

- **行为偏差（behavioral biases）：** 锚定（anchoring）、羊群效应（herding）、处置效应（disposition effect）造成价格调整缓慢
- **机构资金流（institutional flows）：** 养老金再平衡（pension fund rebalancing）、央行干预（central bank interventions）、指数跟踪（index tracking）
- **风险溢价（risk premia）：** 趋势跟踪类似于做多跨式（long a straddle）——无论哪个方向出现大幅波动都能获利
- **危机阿尔法（crisis alpha）：** 在持续的市场错位（market dislocations）期间往往表现较好（2008、2022）

### CTA 模型

商品交易顾问（Commodity Trading Advisors, CTAs）是趋势跟踪的主要机构化实施方式：

```
典型 CTA 结构：
- 4 个资产类别（asset classes）中的 50-100 个高流动性期货市场
- 趋势信号（trend signals）：移动平均线、突破，或时间序列动量（time-series momentum）
- 仓位规模：风险平价（risk parity）/ 波动率目标（volatility targeting）
- 再平衡（rebalancing）：每日
- 典型夏普比率（Sharpe）：0.5-0.8（毛（gross）），0.3-0.5（净（net））
- 关键优势：正偏度（positive skew）、危机阿尔法、与股票的低相关（low correlation to equities）
```

### 趋势强度与 ADX

平均趋向指数（Average Directional Index, ADX）度量趋势强度，而不是方向：

```
ADX 计算：
1. +DM = High_t - High_{t-1}（若为正且 > -DM，否则为 0）
2. -DM = Low_{t-1} - Low_t（若为正且 > +DM，否则为 0）
3. ATR = 14 期平均真实波幅
4. +DI = 100 * EMA(+DM, 14) / ATR
5. -DI = 100 * EMA(-DM, 14) / ATR
6. DX = 100 * |+DI - -DI| / (+DI + -DI)
7. ADX = DX 的 14 期 EMA

解读：
  ADX > 25：强趋势（趋势跟踪系统表现较好）
  ADX 20-25：趋势正在形成
  ADX < 20：无趋势（均值回归（mean-reversion）可能更好）
  ADX 上升：趋势在增强
  ADX 下降：趋势在减弱
```

## 详细方法论

### 移动平均线系统

**单一移动平均线：**
```
当 Price > MA(N) 时买入
当 Price < MA(N) 时卖出/做空

常用周期：MA(50)、MA(100)、MA(200)
MA(200) 被跟踪得最广——判断牛市/熊市（bull/bear）的机构基准
```

**均线交叉：**
```
当快线 MA > 慢线 MA 时买入（金叉（golden cross））
当快线 MA < 慢线 MA 时卖出（死叉（death cross））

经典组合：
  快/慢：10/50、20/50、50/200
  更短 = 响应更快，但假突破（whipsaws）更多
  更长 = 信号更少，假突破更少，滞后（lag）更大

均线类型：
  SMA：简单移动平均（Simple）。各期等权。滞后更大。
  EMA：指数移动平均（Exponential）。近期权重更高。滞后更小。
  DEMA/TEMA：双重/三重指数移动平均（Double/Triple EMA）。进一步降低滞后。
  KAMA：考夫曼自适应（Kaufman Adaptive）。按市场噪声（market noise）调整速度。
  Hull MA：使用加权移动平均（WMA）显著降低滞后。
```

**多重均线包络（multiple MA envelope，Faber 风格）：**
```
计算 N 条移动平均线：MA(20)、MA(50)、MA(100)、MA(150)、MA(200)
Signal = 位于当前价格之下的均线占比
  5/5：强上升趋势——满仓
  3/5 或 4/5：中等趋势——部分仓位
  0/5 或 1/5：强下降趋势——空仓或做空
```

### 通道突破系统

**唐奇安通道（Donchian Channel，海龟交易）：**
```
上轨：过去 N 期的最高高点
下轨：过去 N 期的最低低点
中轨：(Upper + Lower) / 2

入场：价格向上突破 N 期高点时买入
      价格向下跌破 N 期低点时卖出
出场：价格向下跌破 M 期低点时平多（M < N）
      价格向上突破 M 期高点时平空

海龟交易原始规则：
  系统 1：N=20（入场），M=10（出场）
  系统 2：N=55（入场），M=20（出场）
  跳过规则：若上一次突破盈利，则跳过下一次系统 1 信号
```

**肯特纳通道（Keltner Channel）：**
```
中轨：EMA(20)
上轨：EMA(20) + 2 * ATR(10)
下轨：EMA(20) - 2 * ATR(10)

向上突破上轨 = 趋势入场
使用随波动率自适应的通道（ATR），对照固定标准差通道（布林带（Bollinger））
```

### 基于 ATR 的仓位规模

平均真实波幅控制每一笔仓位的风险：

```
True Range = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
ATR(N) = True Range 的 N 期平均

仓位规模计算：
  每笔交易的美元风险 = Account * risk_fraction
  每单位 ATR 对应的美元 = ATR(20) * point_value
  仓位规模 = 每笔交易的美元风险 / (stop_distance_ATR * 每单位 ATR 对应的美元)

示例：
  账户：$1,000,000
  风险比例：1%（每笔交易 $10,000）
  原油的 ATR(20)：$2.50
  点值（point value）：价格每变动 $1 对应 $1,000
  止损距离：2 ATR = 每张合约 $5,000
  仓位：$10,000 / $5,000 = 2 张合约

海龟交易单位：
  1 个单位 = 账户的 1% / (ATR * point_value)
  每个市场最多 4 个单位，每个相关组（correlated group）最多 10 个单位
```

### 波动率缩放（volatility scaling）

```
目标波动率方法：
  target_vol = 10% 年化（CTA 的典型取值）
  current_vol = realized_vol 或 ATR 隐含波动率
  position_scalar = target_vol / current_vol

  波动率更高 → 仓位更小
  波动率更低 → 仓位更大
  使风险贡献在不同工具与不同时间上保持恒定

应用于多资产趋势组合：
  对每个工具 i：
    signal_i = sign(趋势指标)
    vol_i = 工具 i 的已实现波动率（realized vol）
    weight_i = signal_i * (target_vol / vol_i) / N_instruments
```

### CTA 组合构建

```
市场选择标准：
  - 流动性充足（未平仓量（open interest）、成交量（volume））
  - 数据可得（至少 10 年以上）
  - 交易成本（transaction costs）合理
  - 与组合中已有市场的相关性低

典型的板块配置：
  股票：       风险预算的 20-25%（5-8 个市场：ES、NQ、NK、SX5E、HSI 等）
  固定收益：   25-30%（5-8 个市场：ZN、ZB、Bund、Gilt、JGB 等）
  外汇：       20-25%（6-10 个货币对：EUR、GBP、JPY、AUD、CAD、CHF 等）
  商品：       20-25%（10-15 个市场：CL、GC、SI、NG、Corn、Soy 等）

风险平价原则：
  每个工具贡献相等的风险（按波动率加权（volatility-weighted））
  每个板块贡献大致相等的风险
  避免任何单一市场或板块占据主导

相关性管理：
  各市场的趋势信号彼此相关（风险偏好（risk-on）时全部做多）
  监控组合层面的相关性
  考虑抵消相关仓位（若 ES 已经做多，则降低 NQ）
```

### 管理假突破

假突破（迅速反转的虚假突破（false breakouts））是趋势跟踪的主要成本：

```
假突破缓释：
1. 确认延迟：信号出现后等待 1-3 天再入场
2. 过滤：只沿更长期趋势的方向交易（例如，仅当价格位于 MA(200) 之上时才买入）
3. 波动率过滤：当 ADX < 20（无趋势）时避免入场
4. 带宽过滤：要求价格相对均线移动 X% 之后才触发
5. 多时间框架：仅当短期、中期与长期趋势一致时才入场
6. 初次入场使用较小仓位，确认后再加仓

假突破缓释的代价：
  - 每增加一道过滤都会减少假突破，但同时也会推迟有效入场
  - 有些最好的交易是过滤器会错过的快速行情
  - 在众多市场上做分散化，是最好的假突破缓释
```

## 模板 / 示例

### 趋势跟踪策略报告

```
策略：双均线交叉（50/200 EMA）+ ATR 仓位规模
投资域：40 个高流动性期货（股票、固定收益（FI）、外汇、商品）
区间：2005-2024

--- 业绩 ---
年化收益率：           9.5%
年化波动率：           12.0%
夏普比率：             0.79
最大回撤：             -18.5%
卡玛比率（Calmar Ratio）： 0.51
偏度（Skewness）：     +0.35（正偏——危机阿尔法）
胜率（交易）：         38%（胜率低，盈亏比（payoff ratio）高）
平均盈利 / 平均亏损：  2.8x

--- 危机期表现 ---
2008 年全球金融危机（GFC）： +22%（做空股票，做多债券）
2020 年新冠（COVID）3 月：   -5%（假突破，随后收复）
2022 年加息：                +18%（做空债券，做多商品）

--- 板块贡献 ---
股票：                 2.1% 年化
固定收益：             3.2%
外汇：                 1.8%
商品：                 2.4%

--- 成本分析 ---
年均交易笔数：         320（覆盖全部市场）
估计滑点（slippage）： $850K，对应 $100M
佣金（commission）：   $320K
净夏普比率：           0.62
```

### 系统参数敏感性

```
快线 MA | 慢线 MA | 夏普比率 | 最大回撤 | 每年交易次数 | 胜率
10      | 50      | 0.55     | -22%     | 580          | 35%
20      | 100     | 0.68     | -20%     | 380          | 37%
50      | 200     | 0.79     | -18%     | 220          | 38%
100     | 300     | 0.72     | -16%     | 150          | 40%

观察：更慢的系统夏普比率更高、回撤更低，
但交易笔数更少。50/200 组合是稳健的适宜区间（sweet spot）。
```

## 质量关口（quality gate）

在部署趋势跟踪策略之前：

- [ ] 趋势信号产生正偏度（大额盈利多于大额亏损）
- [ ] 系统已在多个资产类别与多个时期上测试
- [ ] 已实施基于 ATR 或波动率的仓位规模
- [ ] 假突破成本已经量化，并且可以接受
- [ ] 交易成本（滑点 + 佣金）已从业绩中扣除
- [ ] 组合已在 20 个以上市场与 4 个以上资产类别上分散
- [ ] 在组合层面监控趋势仓位之间的相关性
- [ ] 已按每个市场与每个板块定义最大仓位限额
- [ ] 已有回撤管理计划（回撤达到 X% 之后降低风险）
- [ ] 系统参数对小幅扰动保持稳健（没有悬崖效应（cliff effects））
