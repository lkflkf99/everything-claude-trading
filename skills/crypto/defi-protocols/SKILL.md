# 去中心化金融（DeFi）协议分析

## 何时启用
- 分析 DeFi 协议机制，以寻找交易或收益（yield）机会
- 评估自动做市商（AMM）设计（Uniswap v3、Curve）、借贷协议（Aave、Compound）或质押（staking）系统
- 评估提供流动性（liquidity provision）的策略，包括集中流动性（concentrated liquidity）与稳定币兑换不变量（stableswap invariant）
- 比较流动性质押（liquid staking）方案（Lido、Rocket Pool），或评估验证者经济（validator economics）

## 核心概念

### 自动做市商（AMM）

**恒定乘积（constant product）（Uniswap v2）：**
- 不变量（invariant）：x * y = k
- 价格冲击（price impact）与交易规模相对于资金池深度（pool depth）的比值成正比
- 流动性提供者（LP）在整个价格区间（price range）(0, infinity) 上均匀提供流动性
- 机制简单，但资本效率低（capital-inefficient）——大部分流动性停留在远离当前价格的位置，处于未被使用的状态

**集中流动性（Uniswap v3）：**
- LP 选择价格区间 [p_lower, p_upper] 来部署资金
- 资本效率（capital efficiency）增益：对于窄区间，相较 v2 最高可达 4000x
- 手续费档位（fee tier）：0.01%（稳定币，stablecoin）、0.05%（相关资产对，correlated pairs）、0.30%（标准，standard）、1.00%（奇异，exotic）
- 头寸（position）管理是主动的——超出区间（out-of-range）的头寸所赚取的手续费为零
- tick 间距（tick spacing）决定粒度（granularity）：对于 0.01% 手续费档位，1 tick = 0.01% 价格变动
- 即时流动性（JIT, just-in-time liquidity）：专业 LP 在同一区块（block）内，围绕大额交易添加或移除流动性

**Curve StableSwap：**
- 不变量混合了恒定乘积与恒定和（constant-sum）：A * n^n * sum(x_i) + D = A * D * n^n + D^(n+1) / (n^n * prod(x_i))
- 放大参数（amplification parameter）A 控制曲线在锚定（peg）附近的平坦程度
- A 越高 = 曲线越平坦 = 锚定附近的滑点（slippage）越低，但资产一旦脱锚（depeg），风险就越高
- Curve v2（CryptoSwap）把适用范围扩展到波动资产对（volatile pairs），并带有内部预言机（oracle）与动态 A
- 计量器（gauge）系统：veCRV（vote-escrowed CRV）持有者对排放（emission）分配进行投票；围绕 gauge 控制权形成 "Curve Wars"

### 借贷协议

**Aave/Compound 机制：**
- 资金利用率（utilization rate）U = total borrows / total deposits
- 利率模型呈折点（kinked）形态：低于最优利用率（optimal utilization）时利率较低，高于最优利用率时利率陡峭
  - Aave：variable rate = base + (U / U_optimal) * slope1 when U < U_optimal
  - Aave：variable rate = base + slope1 + ((U - U_optimal) / (1 - U_optimal)) * slope2 when U >= U_optimal
  - slope2 通常为 slope1 的 10-50x，用以抑制资金利用率达到满额（full utilization）
- 抵押因子（collateral factor，LTV）：决定每种资产的最大借款能力（例如在 Aave v3 上 ETH = 82.5%）
- 清算阈值（liquidation threshold）> LTV——清算触发之前留有缓冲区间
- 清算罚金（liquidation penalty）：5-10% 的奖励用于激励清算人（liquidator）
- 健康因子（health factor）= (collateral * liquidation_threshold) / debt；HF < 1.0 时触发清算

**Aave v3 功能：**
- 效率模式（efficiency mode，e-mode）：相关资产（correlated assets）可以使用更高的 LTV（例如 ETH/stETH 的 LTV 为 93%）
- 隔离模式（isolation mode）：新上架的资产只有有限的可借容量
- Portal：跨链（cross-chain）流动性桥接（liquidity bridging）
- 闪电贷（flash loan）：无抵押（uncollateralized）的单区块贷款；手续费为 0.05%（Aave）、0%（部分分叉，fork）

### 质押与流动性质押

**验证者经济（Ethereum 权益证明，PoS）：**
- 每位验证者的最低质押量为 32 ETH
- 奖励：证明奖励（attestation）+ 区块提议奖励（block proposal）+ 最大可提取价值（MEV）小费（tip）
- 当前收益大约为 3-5% 年化利率（APR），具体取决于质押总量
- 罚没（slashing）风险：双重签名（double-signing）、包围投票（surround voting）——罚金与同期发生的罚没事件相关
- 提款队列（withdrawal queue）：等待时间长短不一，取决于流失限额（churn limit）

**流动性质押：**
- Lido（stETH）：重定基数（rebasing）代币，余额每日更新，并带有约 90% 市场份额（market share）的风险
- Rocket Pool（rETH）：汇率模型（exchange-rate model），价值持续累积，去中心化程度更高（无需许可的节点运营者，permissionless node operators）
- 质押衍生品（staking derivative）定价：交易价格应接近 1:1，但在市场承压（market stress）或提款延迟期间会出现折价（discount）
- stETH/ETH 锚定风险：2022 年期间，由于 3AC 的被迫抛售以及提款不确定性，折价达到约 5%

## 方法论

### 协议评估框架
1. **机制设计（mechanism design）** — 从数学上理解不变量 / 利率模型
2. **TVL 分析** — 总锁仓价值（total value locked，TVL）、TVL 趋势，以及按资金池 / 市场划分的 TVL 集中度
3. **收入分析** — 协议收入与代币持有人收入；费用开关（fee switch）的状态
4. **风险评估** — 智能合约（smart contract）风险（审计（audit）、漏洞赏金（bug bounty））、预言机风险、治理（governance）风险
5. **竞争定位** — 市场份额、护城河（moat）、分叉风险、激励可持续性（incentive sustainability）

### LP 头寸管理（Uniswap v3）
```
1. 根据预期波动率（expected volatility）选择交易对（pair）与手续费档位
2. 分析历史价格分布，以确定区间
   - 区间越窄 = 价格处于区间内时手续费越多，价格脱离区间时再平衡（rebalancing）越频繁
   - 经验法则：将区间设定为覆盖预期价格变动的 1-2 个标准差（standard deviation）
3. 计算预期手续费收入相对于无常损失（impermanent loss，IL）
4. 监控头寸：当价格离开区间，或当 IL 超过手续费收入时，进行再平衡
5. 计入燃料费（gas）成本——在 Ethereum 主网（mainnet）上进行再平衡的成本为 $20-100+
```

### 借贷策略分析
```
1. 比较同一资产在各协议上的供给利率与借款利率（supply/borrow rate）
2. 检查资金利用率——高利用率意味着提款风险（withdrawal risk）
3. 评估清算风险：针对抵押品（collateral）回撤（drawdown）情景建立模型
4. 考虑循环杠杆（recursive leverage）：存入 ETH，借入稳定币，再买入更多 ETH
   - 有效杠杆（effective leverage）= 1 / (1 - LTV)；80% LTV = 5x 有效杠杆
   - 风险：若抵押品急剧下跌，则出现连环清算（liquidation cascade）
5. 监控可能改变参数的治理提案（governance proposal）
```

## 示例

### 示例 1：Curve 资金池分析
```
资金池：3pool (DAI/USDC/USDT)
A 参数：2000
TVL：$500M
日成交量：$50M
手续费：0.01%

分析：
- 成交量/TVL 比率：每日 10%——利用率处于健康水平
- 在 A=2000 时，$1M 交易的滑点：约 0.002%
- 手续费带来的基础年化收益率（APY）：约 3.65%（10% * 0.01% * 365）
- CRV 排放额外增加 5-15%，具体取决于 gauge 权重与加速（boost）
- 风险：USDT 脱锚将打破放大参数假设
```

### 示例 2：Aave 循环杠杆
```
策略：存入 ETH，借入 USDC，买入 ETH，然后重复
Aave v3 上的 ETH LTV：82.5%
清算阈值：86%

3 轮循环（loop）：
- 存入 10 ETH（$20,000）
- 借入 $16,500 USDC（82.5% LTV）
- 买入 8.25 ETH，并存入
- 借入 $13,612 USDC
- 买入 6.8 ETH，并存入

有效头寸：以 10 ETH 抵押品承担约 25 ETH 敞口（exposure）（2.5x 杠杆）
清算价格：大约低于入场价（entry）18%
借款成本：按借款总额计约 3% APR
杠杆净成本：约 3% * 1.5（杠杆倍数，leverage ratio）= 4.5% 年化拖累（annual drag）

风险：若 ETH 迅速下跌 15%+，将发生连环清算。健康因子
必须持续监控。若该交易对可用，请考虑使用 Aave 的
e-mode。
```

### 示例 3：流动性质押套利（arbitrage）
```
观察：
- stETH 在 Curve 上以 0.97 ETH 的价格交易
- Lido 已启用提款，队列时间为 3 天
- 公允价值（fair value）：1.0 ETH（减去较小的时间价值折价，time value）

交易：
- 在 Curve 以 0.97 买入 stETH
- 向 Lido 提交提款请求
- 提款期结束后收到 1.0 ETH
- 利润：3% 减去燃料费成本，以及资金锁定（capital lockup）的机会成本（opportunity cost）

风险因素：
- 需求较高时，提款队列可能延长
- 提款过程中存在智能合约风险
- 在提款完成之前，stETH 折价可能进一步扩大
```

## 质量门禁（quality gate）

在向 DeFi 协议部署资金之前，请核实：

- [ ] 智能合约已由 2 家以上信誉良好的机构完成审计，并且设有正在进行的漏洞赏金
- [ ] 协议已上线 6 个月以上，且未出现严重的漏洞利用（exploit）（或相关漏洞利用已被修补并完成事后复盘，post-mortem）
- [ ] 利率模型或 AMM 不变量已从数学上被理解，而不仅仅是被描述
- [ ] 已针对符合现实的价格情景对无常损失与手续费收入进行建模，而不仅仅是历史情景
- [ ] 已针对 2-3 个标准差（sigma）的价格变动，对清算阈值与健康因子进行压力测试（stress test）
- [ ] 已识别预言机依赖——Chainlink 对比时间加权平均价格（TWAP）对比自定义预言机，以及它们的失效模式（failure mode）
- [ ] 头寸管理的燃料费成本已计入预期回报（expected return）
- [ ] 已评估治理风险——参数是否可能经由治理投票、在较短的时间锁（timelock）内被更改？
- [ ] 已评估集中度风险（concentration risk）——你的头寸占 TVL 的百分比是多少？你能否在不推动市场的情况下退出？
- [ ] 已考虑监管风险——协议的司法辖区（jurisdiction）、了解你的客户（KYC）要求，以及遭受制裁（sanctions）的可能性
