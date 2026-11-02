# 二叉树（binomial tree）期权定价

> CRR 模型、多步树（multi-step tree）、美式期权（American option）、提前行权边界（early exercise boundary）、校准（calibration），以及向 BSM 的收敛（convergence）。

## 何时启用

- 用户为不存在闭式解（closed-form solution）的美式期权定价
- 借助离散模型（discrete model）讲授或解释期权定价的直觉
- 为带有离散股息（discrete dividend）或复杂行权特征（complex exercise feature）的期权定价
- 校准树参数（tree parameter），使之与市场价格（market price）相符
- 理解付息股票（dividend-paying stock）上美式看跌期权（American put）与美式看涨期权（American call）的提前行权边界
- 用树的结果校验其他定价方法（蒙特卡洛（Monte Carlo）、有限差分（finite difference））

## 核心概念

### 二叉树模型的直觉

在每个时间步（time step），股价（stock price）可以移动到两种状态之一：
- 上涨状态（up state）：S_u = S * u（上涨因子（up factor））
- 下跌状态（down state）：S_d = S * d（下跌因子（down factor））
- 上涨变动（up move）的风险中性概率（risk-neutral probability）：p = (exp(r*dt) - d) / (u - d)
- 每个节点（node）上的期权价值（option value）：风险中性概率下的折现期望值（discounted expected value）
- 在到期（expiry）时：期权价值 = 内在价值（intrinsic value）（看涨期权（call）为 max(S-K, 0)，看跌期权（put）为 max(K-S, 0)）
- 从到期日倒推至今日，逐一计算每个节点的期权价值

### Cox-Ross-Rubinstein（CRR）参数化（parameterization）

保证该树收敛到几何布朗运动（geometric Brownian motion, GBM）的标准参数化：
- u = exp(sigma * sqrt(dt))
- d = 1/u = exp(-sigma * sqrt(dt))
- p = (exp(r*dt) - d) / (u - d)
- dt = T/N，其中 N = 时间步数

性质：
- u * d = 1（重组树（recombining tree）——树会重新汇合，从而使节点数量保持在可控范围内）
- 经过 N 步之后：路径（path）数为 2^N，但由于重组（recombination），互异的终端价格（terminal price）只有 N+1 个
- 终端股价：当 j = 0, 1, ..., N 时，为 S * u^j * d^(N-j)
- 到达该节点（N 步中有 j 次上涨）的风险中性概率：C(N,j) * p^j * (1-p)^(N-j)

### 替代参数化

**Jarrow-Rudd（等概率（equal probability））**
- p = 0.5
- u = exp((r - sigma^2/2)*dt + sigma*sqrt(dt))
- d = exp((r - sigma^2/2)*dt - sigma*sqrt(dt))
- 某些收敛性质更好，但使用较少

**Tian（矩匹配（moment-matching））**
- 匹配对数正态分布（log-normal distribution）的前三阶矩（first three moments）
- u = 0.5 * exp(r*dt) * M2 * (M2 + 1 + sqrt(M2^2 + 2*M2 - 3))
- d = 0.5 * exp(r*dt) * M2 * (M2 + 1 - sqrt(M2^2 + 2*M2 - 3))
- M2 = exp(sigma^2 * dt)
- 对某些类型的期权，收敛速度快于 CRR

**Leisen-Reimer**
- 旨在尽量减小收敛过程中的振荡（oscillation）
- 对来自 BSM 的 d1 与 d2 使用 Peizer-Pratt 反演（Peizer-Pratt inversion）
- 即便 N 仅为中等步数（50-100 步），收敛也非常平滑

## 方法论

### 二叉树上的欧式期权（European option）定价

1. **构建股价树（stock tree）**：计算每个节点 (i, j) 的股价，其中 i = 时间步，j = 上涨次数
   - S(i, j) = S_0 * u^j * d^(i-j)，其中 j = 0, 1, ..., i
2. **计算终端收益（terminal payoff）**：在第 N 步，看涨期权的 payoff(N, j) = max(S(N,j) - K, 0)
3. **倒向归纳（backward induction）**：对于 i = N-1, N-2, ..., 0：
   - V(i, j) = exp(-r*dt) * [p * V(i+1, j+1) + (1-p) * V(i+1, j)]
4. **期权价格（option price）**：根节点（root node）处的 V(0, 0)

### 美式期权定价

关键的补充是：在每个节点，比较持有价值（holding value）与行权价值（exercise value）。

1. 构建股价树（与欧式相同）
2. 终端收益（与欧式相同）
3. 带有提前行权检验的倒向归纳：
   - 继续持有价值（continuation value）：C(i, j) = exp(-r*dt) * [p * V(i+1, j+1) + (1-p) * V(i+1, j)]
   - 行权价值：E(i, j) = 看跌期权取 max(K - S(i,j), 0)；看涨期权取 max(S(i,j) - K, 0)
   - V(i, j) = max(C(i, j), E(i, j))
4. 若 E(i, j) > C(i, j)，则在该节点提前行权是最优的
5. 提前行权为最优的节点集合定义了提前行权边界

### 提前行权边界

**美式看跌期权**
- 当期权处于足够深的实值（in the money, ITM）、时间价值（time value）为负时，行权总是最优的
- 临界股价（critical stock price）S*(t)：若 S < S*(t) 则行权
- 随着 t -> T，S*(t) 下降（边界在到期时收敛到 K）
- 当 r > 0 时：S*(T) = K（到期时对平值（at the money, ATM）看跌期权行权）
- 该边界平滑，并朝 K 单调上升

**付息股票上的美式看涨期权**
- 提前行权可能恰好在除息日（ex-dividend date）之前是最优的
- 若股息超过期权的时间价值，则行权
- 经验法则：若股息 > K * (1 - exp(-r*dt_remaining))，则行权是最优的
- 对于连续股息率（continuous dividend yield）q：若 q > 0，则对所有 t 都存在提前行权边界

**无股息股票上的美式看涨期权**
- 提前行权永远不是最优的（不存在该边界）
- 美式看涨期权 = 欧式看涨期权（不存在提前行权溢价（early exercise premium））
- 证明：当 r > 0 时，看涨期权价值 >= S - K*exp(-rT) > S - K（内在价值）

### 树上的离散股息

**方法 1：在除息节点下调股价**
- 在除息这一步，从所有股价中减去已知股息 D
- 问题：支付股息之后，树不再重组（分支发生分裂）
- 修正：使用 Black 近似（Black approximation）——将 S_0 减去股息的现值（present value, PV），并在调整后的 S 上构建树

**方法 2：股息率方法（dividend yield approach）**
- 将股息建模为按比例下调（proportional reduction）：在除息日 S -> S * (1 - delta)
- 树仍然保持重组
- 对于支付固定金额股息（fixed dollar dividend）的股票，准确度较低

**方法 3：插值法（interpolation method）**
- 构建重组树，在股息日于完成股息调整后的节点之间进行插值
- 更准确，但计算上更为复杂

### 向 BSM 的收敛

- 当 N -> infinity 时，CRR 二叉树价格对欧式期权收敛到 BSM 价格
- 收敛速率（rate of convergence）：O(1/N)——误差（error）随步数成比例下降
- 振荡：CRR 在真实值附近振荡（偶数 N 与奇数 N 会系统性地给出不同的价格）
- 实务中：对大多数期权，N = 200-500 步可使精度落在 1 美分以内
- Richardson 外推（Richardson extrapolation）：将 N 步与 N+1 步的价格取平均，以抵消振荡
- Leisen-Reimer：在 N = 50-100 时即可平滑收敛

## 示例

### 欧式看涨期权的三步 CRR 树
```
参数：S=100, K=100, r=5%, sigma=30%, T=0.75（3 个季度）
dt = 0.25, u = exp(0.30*sqrt(0.25)) = 1.1618, d = 1/u = 0.8607
p = (exp(0.05*0.25) - 0.8607) / (1.1618 - 0.8607) = 0.5073

股价树：
  t=0:     100.00
  t=0.25:  116.18 / 86.07
  t=0.50:  135.00 / 100.00 / 74.08
  t=0.75:  156.83 / 116.18 / 86.07 / 63.76

T 时刻的看涨收益：
  156.83-100=56.83, 116.18-100=16.18, max(86.07-100,0)=0, max(63.76-100,0)=0

倒向归纳：
  t=0.50: (0.5073*56.83 + 0.4927*16.18)*exp(-0.0125) = 36.74
          (0.5073*16.18 + 0.4927*0)*exp(-0.0125) = 8.11
          (0.5073*0 + 0.4927*0)*exp(-0.0125) = 0
  t=0.25: (0.5073*36.74 + 0.4927*8.11)*exp(-0.0125) = 22.35
          (0.5073*8.11 + 0.4927*0)*exp(-0.0125) = 4.06
  t=0:    (0.5073*22.35 + 0.4927*4.06)*exp(-0.0125) = 13.18

树价格：$13.18
BSM 价格：$13.15（即便只有 3 步也已经很接近）
```

### 美式看跌期权的提前行权
```
参数相同，但定价的是看跌期权（K=100）：

T 时刻的看跌收益：0, 0, max(100-86.07,0)=13.93, max(100-63.76,0)=36.24

带有提前行权检验的倒向归纳：
  t=0.50（S=74.08）：
    继续持有价值：(0.5073*13.93 + 0.4927*36.24)*exp(-0.0125) = 24.60
    行权价值：100-74.08 = 25.92
    价值 = max(24.60, 25.92) = 25.92 ***提前行权***

  t=0.50（S=100）：继续持有价值=6.99，行权价值=0，价值=6.99
  t=0.50（S=135）：继续持有价值=0，行权价值=0，价值=0

美式看跌期权相对欧式的溢价：$0.35（来自提前行权价值）
```

### 收敛分析
```
欧式看涨期权（S=100, K=100, r=5%, sigma=30%, T=1）：
BSM 精确值 = $14.23

N=10:   $14.35（误差 = +$0.12）
N=50:   $14.25（误差 = +$0.02）
N=100:  $14.24（误差 = +$0.01）
N=200:  $14.23（误差 < $0.005）
N=500:  $14.23（误差 < $0.002）

Richardson 外推（N=100, N=101）：$14.231（误差 < $0.001）
Leisen-Reimer（N=51）：$14.231（误差 < $0.001）
```

## 质量关卡

- CRR 参数必须满足：0 < p < 1（验证风险中性概率有效）
- 树必须重组：在数值精度（numerical precision）之内验证 u*d = 1
- 美式期权价格必须 >= 欧式期权价格（验证提前行权溢价为非负）
- 无股息股票上的美式看涨期权必须等于欧式看涨期权（验证不发生提前行权）
- 必须验证收敛：增大 N，直到相邻的 N 之间价格变化小于 $0.01
- 生产环境定价（production pricing）至少使用 N=200 步；精确基准值（benchmark value）使用 N=500 及以上
- 提前行权边界必须平滑且单调（不规则的边界表明实现有误（implementation error））
- 离散股息的处理必须在除息节点正确调整股价
- 针对欧式期权，用 BSM 进行校验：树价格必须收敛到 BSM，相差在 0.1% 以内
- 当计算时间有限时，应使用 Richardson 外推或 Leisen-Reimer
