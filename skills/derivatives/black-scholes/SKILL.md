# Black-Scholes-Merton 模型与扩展

> BSM 推导直觉、公式、看涨看跌平价（put-call parity）、希腊值（Greeks）、局限性，以及针对股息（dividends）、美式期权（American options）与隐含波动率（implied volatility）的扩展。

## 何时启用

- 用户为欧式期权（European options）定价或计算隐含波动率
- 推导或解释用于对冲（hedging）的 BSM 希腊值
- 理解 BSM 假设及其失效情形
- 将 BSM 扩展到股息、离散对冲（discrete hedging）或跳跃
- 计算看涨看跌平价关系或识别套利（arbitrage）
- 讲授或解释期权定价基础

## 核心概念

### BSM 推导直觉

Black-Scholes-Merton 模型建立在三大支柱之上：

1. **几何布朗运动（Geometric Brownian Motion, GBM）**：股价（stock price）遵循 dS = mu*S*dt + sigma*S*dW
   - 对数收益率（log returns）服从正态分布：ln(S_T/S_0) ~ N((mu - sigma^2/2)*T, sigma^2*T)
   - 路径连续、没有跳跃——这是一项关键局限

2. **无套利（no-arbitrage）/ 风险中性定价（risk-neutral pricing）**：用期权与 delta 股构造无风险组合（riskless portfolio）
   - 由无套利，该组合赚取无风险利率（risk-free rate）
   - 在风险中性测度（risk-neutral measure）下，S 的漂移变为 r（无风险利率），而不是 mu
   - 期权价格 = 风险中性测度下支付（payoff）的贴现期望

3. **连续对冲（continuous hedging）**：delta 对冲被连续再平衡（无交易成本（transaction costs））
   - 实务中，离散对冲引入与 gamma * (dS)^2 成比例的对冲误差（hedging error）

### BSM 公式

**欧式看涨期权（European call）**：
C = S * N(d1) - K * exp(-rT) * N(d2)

**欧式看跌期权（European put）**：
P = K * exp(-rT) * N(-d2) - S * N(-d1)

其中：
- d1 = [ln(S/K) + (r + sigma^2/2)*T] / (sigma * sqrt(T))
- d2 = d1 - sigma * sqrt(T)
- N(x) = 标准正态分布累积函数（cumulative standard normal distribution）
- S = 现货价格（spot price），K = 行权价（strike），r = 无风险利率，T = 到期时间（time to expiry），sigma = 波动率（volatility）

**解释**：
- N(d2) = 期权到期时处于实值（in-the-money）的风险中性概率（risk-neutral probability）
- S * N(d1) = 在行权条件下收到股票的现值（present value）
- K * exp(-rT) * N(d2) = 在行权条件下支付行权价的现值
- 看涨期权的 delta = N(d1)；看跌期权的 delta = N(d1) - 1

### 看涨看跌平价

对于行权价与到期日相同的欧式期权：
- C - P = S - K * exp(-rT)
- 无论使用何种模型，均由无套利成立
- 若被违背，则构造套利：买入便宜的一侧，卖出昂贵的一侧
- 含股息时：C - P = S - PV(dividends) - K * exp(-rT)
- 看涨看跌平价对美式期权并不成立（提前行权（early exercise）会造成不等式）

### BSM 希腊值（解析式）

**Delta**：dC/dS = N(d1)（看涨期权）；N(d1) - 1（看跌期权）
**Gamma**：d^2C/dS^2 = phi(d1) / (S * sigma * sqrt(T)) — 看涨与看跌相同
**Theta**：dC/dt = -(S * phi(d1) * sigma) / (2*sqrt(T)) - r * K * exp(-rT) * N(d2)（看涨期权）
**Vega**：dC/d(sigma) = S * phi(d1) * sqrt(T) — 看涨与看跌相同
**Rho**：dC/dr = K * T * exp(-rT) * N(d2)（看涨期权）

其中 phi(x) = 标准正态密度函数（standard normal density function）。

### BSM 假设与局限

1. **波动率恒定（constant volatility）**：真实市场呈现波动率微笑/偏斜（volatility smile/skew）——虚值看跌期权（OTM puts）的隐含波动率更高
2. **对数正态收益（log-normal returns）**：真实收益具有肥尾（fat tails）与负偏度（negative skewness）
3. **无跳跃**：真实价格会发生跳跃（财报、宏观事件）——跳跃扩散模型（jump-diffusion models）处理这一问题
4. **连续交易（continuous trading）**：离散对冲引入损益（P&L）噪声
5. **无交易成本**：实务中，对冲成本使 BSM 价格偏低
6. **利率恒定（constant interest rates）**：对债券/利率的长久期期权较为重要
7. **无股息**：基础 BSM 假设没有股息（可以修正）
8. **欧式行权（European exercise）**：BSM 不能直接为美式期权定价

## 方法论

### 隐含波动率的计算

隐含波动率是使 BSM 价格等于所观察市场价格的 sigma。

**牛顿-拉夫森法（Newton-Raphson）**：
1. 从初始猜测 sigma_0 开始（例如 20%）
2. 计算 BSM 价格 C(sigma_n) 与 vega V(sigma_n)
3. 更新：sigma_{n+1} = sigma_n - (C(sigma_n) - C_market) / V(sigma_n)
4. 当 |C(sigma_n) - C_market| < 容差（tolerance）（例如 0.01）时收敛
5. 通常在 3-5 次迭代内收敛
6. 边界情形：深度实值/虚值（deep ITM/OTM）期权的 vega 很低——可能无法收敛；以二分法（bisection）作为后备

**Brenner-Subrahmanyam 近似（Brenner-Subrahmanyam approximation）**（平值（at-the-money, ATM）的快速初始猜测）：
- sigma_approx = C * sqrt(2*pi) / (S * sqrt(T))
- 对接近平值的期权，精度在 1-2 个波动率点（vol points）以内

### BSM 扩展

**股息（Merton 模型）**
- 连续股息率（continuous dividend yield）q：在 BSM 公式中用 S * exp(-qT) 替换 S
- d1 = [ln(S/K) + (r - q + sigma^2/2)*T] / (sigma * sqrt(T))
- 离散股息（discrete dividends）：将 S 减去到期前预期股息的现值
- 对指数期权（index options），连续股息率近似效果良好

**美式期权**
- 无股息股票上的美式看涨期权 = 欧式看涨期权（提前行权永远不是最优）
- 美式看跌期权，以及有股息股票上的看涨期权，可能被提前行权
- 美式期权没有 BSM 闭式解（closed-form solution）
- 近似方法：Barone-Adesi and Whaley、Bjerksund-Stensland
- 精确方法：二叉树（binomial trees）、有限差分（finite differences）

**Merton 跳跃扩散（Merton's jump-diffusion）**
- dS/S = (mu - lambda*k)*dt + sigma*dW + J*dN
- J = 跳跃幅度（jump size，对数正态），dN = 强度为 lambda 的泊松过程（Poisson process），k = E[e^J - 1]
- 产生肥尾与短期限波动率微笑
- 期权价格 = 调整方差后的 BSM 价格加权和：sum over n of (exp(-lambda'*T) * (lambda'*T)^n / n!) * BSM(sigma_n)
- sigma_n^2 = sigma^2 + n * delta^2 / T

**随机波动率（stochastic volatility）（Heston）**
- dS = mu*S*dt + sqrt(v)*S*dW_1
- dv = kappa*(theta - v)*dt + xi*sqrt(v)*dW_2, corr(dW_1, dW_2) = rho
- 产生波动率微笑与期限结构（term structure）
- 通过特征函数（characteristic function）与快速傅里叶变换（fast Fourier transform, FFT）得到半解析解（semi-analytical solution）
- 参数：kappa（均值回复速度（mean reversion speed）），theta（长期波动率（long-run vol）），xi（波动率的波动率（vol of vol）），rho（现货-波动率相关性（spot-vol correlation）），v_0（初始波动率（initial vol））

### 由 BSM 得到的波动率曲面

- 对每个有交易的行权价与到期日计算隐含波动率
- 绘制隐含波动率相对价值状态（moneyness）（K/S 或 delta）与到期期限（maturity）的图形
- 微笑：隐含波动率沿行权价呈 U 形（股指：偏斜——看跌高于看涨）
- 期限结构：隐含波动率随到期期限变化（平静市场中通常向上倾斜）
- 波动率曲面（volatility surface）是市场对 BSM 恒定波动率假设的修正

## 示例

### BSM 定价
```
S = $100, K = $105, r = 5%, T = 0.5 年, sigma = 25%

d1 = [ln(100/105) + (0.05 + 0.0625/2)*0.5] / (0.25 * sqrt(0.5))
   = [-0.04879 + 0.04063] / 0.17678
   = -0.00816 / 0.17678 = -0.04615

d2 = -0.04615 - 0.17678 = -0.22293

N(d1) = 0.4816, N(d2) = 0.4118

看涨期权 = 100 * 0.4816 - 105 * exp(-0.025) * 0.4118
     = 48.16 - 105 * 0.9753 * 0.4118
     = 48.16 - 42.16 = $6.00

看跌期权（经由看涨看跌平价）= 6.00 - 100 + 105 * 0.9753 = $8.41
```

### 用牛顿-拉夫森法计算隐含波动率
```
市场看涨期权价格：$7.50（参数与上文相同，但 sigma 未知）

迭代 1：sigma_0 = 0.20
  BSM 价格 = $4.85，vega = 27.5
  sigma_1 = 0.20 - (4.85 - 7.50) / 27.5 = 0.20 + 0.0964 = 0.2964

迭代 2：sigma_1 = 0.2964
  BSM 价格 = $7.35，vega = 28.1
  sigma_2 = 0.2964 - (7.35 - 7.50) / 28.1 = 0.2964 + 0.0053 = 0.3017

迭代 3：sigma_2 = 0.3017
  BSM 价格 = $7.49，vega = 28.1
  sigma_3 = 0.3017 + 0.0004 = 0.3021

收敛：隐含波动率 = 30.2%
```

### Delta 对冲损益归因
```
多头 100 张看涨期权，delta = 0.50，gamma = 0.03，theta = -$150/日，vega = $200/波动率点
对冲：空头 50 股

第 1 日：股价变动 +$2
  Delta 损益：100 * 0.50 * $2 - 50 * $2 = $0（已对冲）
  Gamma 损益：0.5 * 100 * 0.03 * $4 = $6
  Theta 损益：-$150
  净损益：-$144

gamma 损益（$6）较小，因为 $2 的变动处于正常范围之内。
要使 gamma 剥头皮（gamma scalping）获利，需要已实现波动率（realized vol）> 隐含波动率。
```

## 质量门槛

- BSM 只应作为基准使用；真实定价时始终承认微笑/偏斜效应
- 隐含波动率必须收敛到 0.01% 的精度以内；用独立定价器（pricer）核验
- 看涨看跌平价必须在买卖价差（bid-ask spread）以内成立；违背表明数据错误或存在套利
- 欧式期权的希腊值必须由 BSM 解析计算（除非用于验证，否则不用有限差分）
- 对美式期权，不要使用 BSM——使用二叉树或有限差分方法
- 股息处理必须与实际股息日程（dividend schedule）一致（个股用离散股息，指数用连续收益率）
- 当 BSM 隐含波动率在不同行权价之间差异显著（>5 个波动率点）时，注明 BSM 正在失效，需要随机波动率或局部波动率（local volatility）模型
- 对照已知测试用例验证 BSM 实现（例如，平值看涨期权近似 = S * sigma * sqrt(T) * 0.4）
- 记录 BSM 计算中使用的全部输入假设（利率曲线（rate curve）、股息率（dividend yield）、借券成本（borrow cost））
