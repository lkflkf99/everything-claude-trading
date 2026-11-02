# 波动率曲面（volatility surface）构建与分析

> 隐含波动率曲面（implied volatility surface）、微笑（smile）/偏斜（skew）、SVI 参数化、SABR 模型、粘性行权价（sticky strike）与粘性 delta（sticky delta）、曲面动态（surface dynamics），以及套利约束（arbitrage constraints）。

## 何时启用

- 用户正在构建或校准隐含波动率曲面
- 分析波动率微笑、偏斜或期限结构（term structure）的形态
- 在 SVI、SABR 或其他曲面模型之间进行选择
- 理解粘性行权价与粘性 delta 的动态，以便用于对冲（hedging）
- 检查波动率曲面是否存在套利违规（蝶式（butterfly）、日历价差（calendar spread））
- 为未挂牌的行权价（strikes）或到期日（expiries）对隐含波动率做插值（interpolation）或外推（extrapolation）

## 核心概念

### 隐含波动率曲面

隐含波动率曲面将全部行权价 K 与到期期限 T 映射为 sigma_IV(K, T)：

- **微笑**：相对于平值（at-the-money, ATM），虚值看跌期权（out-of-the-money puts, OTM puts）与虚值看涨期权（OTM calls）的隐含波动率（implied volatility, IV）更高——典型见于外汇（FX）与短期限股指
- **偏斜**：隐含波动率从低行权价到高行权价单调下降——股指的主导形态
- **期限结构**：隐含波动率随期限变化——通常向上倾斜（升水（contango）），在压力时期可以倒挂
- **压力下偏斜变陡**：市场抛售时，看跌偏斜变得更加显著
- **压力下期限结构倒挂**：短期限波动率飙升至长期限波动率之上

### 微笑/偏斜为何存在

1. **肥尾（fat tails）**：真实收益具有超额峰度（excess kurtosis）——虚值期权的价值高于 BSM 的预测
2. **负偏度（negative skewness）**：权益收益呈左偏——虚值看跌期权尤其有价值
3. **供需（supply/demand）**：机构对下行保护（看跌期权）的需求推高看跌期权的隐含波动率
4. **杠杆效应（leverage effect）**：股价下跌时，公司杠杆上升，波动率随之升高
5. **跳跃风险（jump risk）**：崩盘风险未被 BSM 捕捉；虚值看跌期权补偿持有人所承担的跳跃风险
6. **随机波动率（stochastic volatility）**：现货-波动率相关性（spot-vol correlation）（权益市场为负）会产生偏斜

### 曲面坐标

**基于行权价（strike-based）**：sigma(K, T) — 直观，但依赖于尺度（scale-dependent）
**价值状态（moneyness）**：sigma(K/S, T) 或 sigma(K/F, T)，其中 F = 远期价格（forward price）— 与尺度无关（scale-independent）
**基于 delta（delta-based）**：sigma(delta, T) — 外汇市场常用（25-delta 看跌、平值、25-delta 看涨）
**对数价值状态（log-moneyness）**：sigma(ln(K/F), T) — 对称，用于 SVI 参数化
**标准化价值状态（standardized moneyness）**：x = ln(K/F) / (sigma_ATM * sqrt(T)) — 跨期限做归一化

## 方法论

### SVI（Stochastic Volatility Inspired）参数化

Gatheral 的 SVI 将总隐含方差（total implied variance）w(k) = sigma^2 * T 参数化为对数价值状态 k = ln(K/F) 的函数：

w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma^2))

参数：
- a：整体方差水平
- b：翼部（wings）斜率（控制虚值期权的方差上升有多快）
- rho：旋转（rotation）/偏斜（-1 到 1；权益偏斜为负）
- m：平移（translation）（使微笑沿水平方向移动）
- sigma：平值区域的平滑程度（控制顶点（vertex）处的曲率（curvature））

性质：
- 翼部呈线性：当 k -> +/- infinity 时，w(k) -> a + b*(rho +/- 1)*(k - m)
- 最小方差位于 k = m - rho*sigma/sqrt(1-rho^2)
- 每个到期切片（expiry slice）5 个参数——简约（parsimonious）但灵活

**SSVI（Surface SVI）**
- 以更少的参数将 SVI 扩展到整张曲面
- 参数化 theta(T)（平值总方差（ATM total variance））与 phi(theta)（翼部形状）
- 由构造保证日历价差无套利
- w(k, T) = theta/2 * (1 + rho*phi*k + sqrt((phi*k + rho)^2 + (1-rho^2)))

### SABR 模型

SABR（Stochastic Alpha Beta Rho）模型是利率期权与外汇期权的标准模型：

dF = sigma * F^beta * dW_1
d(sigma) = alpha * sigma * dW_2
corr(dW_1, dW_2) = rho

参数：
- alpha（波动率的波动率（vol of vol））：控制微笑的曲率——alpha 越高，微笑越凸（convex）
- beta（CEV 指数）：控制主干（backbone）（平值波动率如何随远期变动）——0 = 正态（normal），1 = 对数正态（lognormal）
- rho（现货-波动率相关性）：控制偏斜——rho 为负 = 向下偏斜
- sigma_0（初始波动率）：平值波动率水平

**Hagan 近似（Hagan's approximation）**给出的隐含波动率：
sigma_B(K) = alpha / (F*K)^((1-beta)/2) * {z/x(z)} * [1 + corrections * T]

其中 z = (alpha/sigma_0) * (FK)^((1-beta)/2) * ln(F/K)，且 x(z) 涉及 rho。

校准：
1. 固定 beta（通常取 0、0.5 或 1，依据市场惯例或主干分析）
2. 将 alpha、rho、sigma_0 拟合到市场报价（平值、25-delta 风险逆转（risk reversal）、25-delta 蝶式）
3. 最小化模型隐含波动率与市场隐含波动率之差的平方和

SABR 的局限性：
- 对极低行权价，Hagan 公式可能产生负密度
- 向极端行权价外推需要谨慎
- 若不做逐到期校准（per-expiry calibration），则无法捕捉期限结构动态

### 波动率曲面上的套利约束

**无蝶式套利（单个到期内）**
- 看涨期权价格对行权价必须为凸：d^2C/dK^2 >= 0
- 等价地：风险中性密度（risk-neutral density）必须处处非负
- 用方差表述：d^2w/dk^2 必须高于某个涉及 dw/dk 的下界
- 当 b > 0 且 |rho| < 1 时，SVI 通常不存在蝶式套利

**无日历价差套利（跨到期）**
- 对每个 k，总方差 w(k, T) 对 T 必须非递减
- 若 T_2 > T_1 时 w(k, T_2) < w(k, T_1)，则存在日历价差套利
- SSVI 由构造处理这一点；逐切片的原始 SVI 需要人工检查

**联合约束**
- 隐含波动率曲面必须在所有点上产生非负的风险中性密度
- 实践中：在细密的行权价与到期网格上做数值检查
- 标记任何违规，并调整参数或在校准中加入惩罚项（penalty terms）

### 粘性行权价相对粘性 delta 的动态

标的变动时，波动率曲面如何移动：

**粘性行权价**（绝对粘性（absolute sticky））：
- 当 S 移动时，sigma(K, T) 保持不变
- 当 S 从 100 移动到 105 时，行权价 K=100 处的波动率并不改变
- 新的平值波动率（位于新的 S=105）从现有曲面上的 K=105 处读取
- 含义：平值波动率随现货沿现有微笑移动而改变
- 对冲：BSM delta 是正确的（波动率不依赖于 S）

**粘性 delta**（相对粘性（relative sticky）/ 粘性价值状态（sticky moneyness））：
- sigma(K/S, T) 保持不变——微笑随标的移动
- 当 S 移动时，平值波动率保持不变（微笑发生平移）
- S=100 时 K=100（平值）的期权，与 S=105 时 K=105 具有相同的隐含波动率
- 含义：固定行权价处的隐含波动率随现货移动而改变
- 对冲：BSM delta 需要调整（dVol/dS 不为零）
- 在大多数市场状态（regimes）下，这对股指期权有更强的经验支持

**对对冲的影响**
- 在粘性行权价下：delta_hedge = BSM_delta
- 在粘性 delta 下：delta_hedge = BSM_delta + vega * dIV/dS
- 调整项 dIV/dS 来自偏斜的斜率
- 对于负偏斜：看涨期权在粘性 delta 下的 delta 大于 BSM delta（离零更远）

## 示例

### SVI 校准
```
SPX 1 个月期权，平值远期 = 4500
市场隐含波动率：
  K=4050 (90%): 28.5%    K=4275 (95%): 23.2%    K=4500 (100%): 19.5%
  K=4725 (105%): 17.8%   K=4950 (110%): 17.2%

SVI 拟合（总方差 w = IV^2 * T）：
  a = 0.0029, b = 0.18, rho = -0.72, m = -0.02, sigma = 0.08

拟合隐含波动率：28.4%, 23.3%, 19.5%, 17.9%, 17.1%
最大误差：0.1 个波动率点（vol point） — 拟合极佳。
负的 rho 捕捉了权益偏斜。
```

### 用于掉期期权（swaptions）的 SABR
```
5Y10Y 掉期期权，平值远期 = 3.5%，市场报价：
  平值波动率：45bp（正态波动率）
  25d 风险逆转：-5bp（偏斜）
  25d 蝶式：+2bp（微笑曲率）

SABR 校准（beta = 0.5 固定）：
  sigma_0 = 0.032, alpha = 0.45, rho = -0.25

模型隐含正态波动率：
  F-100bp: 48.2bp    F-50bp: 46.1bp    平值: 45.0bp
  F+50bp: 44.5bp     F+100bp: 44.8bp
```

### 套利检查
```
对 1M 与 2M 的 SVI 曲面做日历价差检查：
  在 k = -0.10（10% 虚值看跌）：
    w(1M) = 0.0092, w(2M) = 0.0198
    w(2M) > w(1M) — 通过，不存在日历套利

  在 k = -0.30（30% 虚值看跌）：
    w(1M) = 0.0285, w(2M) = 0.0260
    w(2M) < w(1M) — 违规：存在日历价差套利

修正：提高 2M 翼部参数 b，或使用 SSVI 以保证一致性。
```

## 质量门槛

- 校准后的曲面必须把市场报价拟合到 0.5 个波动率点以内（或买卖价差（bid-ask spread）以内）
- 无蝶式套利：在细密行权价网格上验证 d^2C/dK^2 >= 0（每个切片至少 100 个点）
- 无日历价差套利：在每个行权价上验证总方差对 T 非递减
- 风险中性密度必须在所有点上非负——绘图并目视检查
- SVI：校准后验证 b > 0、|rho| < 1，且 sigma > 0
- SABR：验证 Hagan 公式的有效范围；若低行权价密度变为负值则予以标记
- 超出已交易行权价的外推必须记录在案：翼部行为（在方差上呈线性）以及边界
- 必须声明粘性行权价与粘性 delta 假设，并在对冲中一致地加以应用
- 流动性充裕的市场必须在日内（intraday）更新曲面；流动性较差的市场在日终（end-of-day）更新
- 至少对照两种独立的曲面构建方法做交叉验证
- 盯市（mark-to-market）必须使用校准后的曲面；不要在平坦波动率（flat vol）假设下使用原始 BSM
