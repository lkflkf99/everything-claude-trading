# 稳定币（stablecoin）分析

## 何时启用
- 评估稳定币的锚定（peg）机制、储备（reserves）构成与风险画像（risk profile）
- 评估脱锚（depeg）风险因素以及历史上的脱锚事件
- 分析稳定币收益（yield）策略及其风险/收益（risk/return）特征
- 比较各类稳定币设计（法币支持（fiat-backed）、加密资产支持（crypto-backed）、算法型（algorithmic））
- 把稳定币市场动态作为加密市场的宏观指标（macro indicator）加以监控

## 核心概念

### 稳定币分类

**法币支持（托管型，custodial）：**
- **USDT（Tether）** — 按市值（market cap）计规模最大；储备包括现金、短期国债（T-bill）、商业票据（commercial paper）（已缩减）、担保贷款（secured loan）
- **USDC（Circle）** — 由现金和短久期美国国债（short-duration US Treasury）足额支持（fully backed）；每月由 Deloitte 出具鉴证（attestation）
- **BUSD（Paxos/Binance）** — 受纽约州金融服务局（NYDFS）监管；正在清退（wind down）
- **PYUSD（PayPal）** — 受监管，由美国国债和存款支持
- 锚定机制：发行方按与 USD 1:1 铸造（mint）/赎回（redeem）；套利者（arbitrageur）把市场价格维持在接近 $1
- 风险：托管风险（custodial risk）、监管风险（regulatory risk）、储备构成不透明（opacity）、银行合作关系风险（banking relationship risk）

**加密资产支持（去中心化，decentralized）：**
- **DAI（MakerDAO/Sky）** — 以 ETH、WBTC、稳定币和真实世界资产（real-world asset, RWA）超额抵押（over-collateralized）
  - 最低抵押率（collateral ratio）：ETH 金库（vault）为 150%（降至 145% 时清算（liquidation））
  - 稳定费（stability fee）（即利率（interest rate））由治理（governance）设定
  - DSR（DAI Savings Rate，DAI 储蓄利率）为 DAI 持有人提供收益
  - 由 RWA 和 USDC 支持的比例上升 — 引发中心化（centralization）担忧
- **LUSD（Liquity）** — 仅以 ETH 支持，合约不可变（immutable contract），没有治理
  - 最低抵押率：110%
  - 赎回机制（redemption mechanism）：任何人都可以用 LUSD，从风险最高的金库赎回价值 $1 的 ETH
  - 真正去中心化，但规模较小
- **crvUSD（Curve）** — 使用 LLAMMA（Lending-Liquidating AMM Algorithm，借贷-清算自动做市商算法）
  - 软清算（soft liquidation）：价格下跌时，逐步把抵押品（collateral）转换为稳定币
  - 若价格回升，则自动重新补足抵押（re-collateralize）
  - 方法新颖，但风险画像复杂
- 风险：抵押品波动率（volatility）、连环清算（liquidation cascade）、预言机（oracle）失效、治理攻击（governance attack）

**算法型（无抵押（uncollateralized）或部分抵押（partially collateralized））：**
- **历史失败案例：** UST/LUNA（死亡螺旋（death spiral），损失 $40B）、IRON/TITAN、Basis Cash
- **铸币税（seigniorage）模型：** 通过销毁治理代币（governance token）来铸造稳定币；具有反身性（reflexive）— 在扩张（expansion）中有效，在收缩（contraction）中失效
- **部分算法型（fractional-algorithmic）：** FRAX（部分抵押、部分算法）；已转向全额抵押（full collateralization）
- 风险：死亡螺旋风险（信心丧失 -> 赎回 -> 进一步脱锚 -> 更多赎回）

### 锚定机制

**硬锚定（hard peg）（法币支持）：**
```
市场价格 > $1.00：
  - 套利者以 $1.00 的价格向发行方铸造新代币
  - 在市场上以高于 $1.00 的价格卖出
  - 利润把价格拉回 $1.00

市场价格 < $1.00：
  - 套利者在市场上以低于 $1.00 的价格买入
  - 向发行方以 $1.00 赎回
  - 利润把价格拉回 $1.00

要求：发行方必须及时兑付赎回
```

**软锚定（soft peg）（加密资产支持）：**
```
DAI 高于 $1.00：
  - 治理降低稳定费（铸造 DAI 的成本更低）
  - 更多 DAI 被铸造并卖出，从而把价格向下推动
  - 可以下调 DSR，以降低对 DAI 的需求

DAI 低于 $1.00：
  - 治理提高稳定费（持有金库的成本更高）
  - 金库持有人买入 DAI 以偿还债务，从而把价格向上推动
  - 可以上调 DSR，以增加对 DAI 的需求
  - 赎回机制（若可用）提供硬性下限（hard floor）
```

**算法锚定（algorithmic peg）（UST 模型 — 已失败）：**
```
UST 高于 $1.00：
  - 通过销毁价值 $1 的 LUNA 来铸造 UST
  - 以高于 $1.00 的价格卖出 UST
  - 提高 LUNA 的稀缺性（看涨反身性，bullish reflexivity）

UST 低于 $1.00：
  - 销毁 UST，以铸造价值 $1 的 LUNA
  - 在市场上卖出 LUNA
  - 但卖出 LUNA 会压低 LUNA 的价格
  - LUNA 价格崩跌会降低对其支持能力的信心
  - 更多 UST 赎回 -> 铸造更多 LUNA -> 死亡螺旋
```

### 储备分析

**关键储备指标：**
```
储备比率（reserve ratio）= total reserves / total stablecoin outstanding
  >1.0：超额抵押（安全）
  =1.0：足额支持（法币支持型的通行标准）
  <1.0：抵押不足（under-collateralized）（有风险）

储备质量（reserve quality）：
  第 1 档（Tier 1）：现金、隔夜回购（overnight repo）、短期国债
  第 2 档（Tier 2）：更长久期的政府债券（longer-duration government bond）、货币市场基金（money market fund）
  第 3 档（Tier 3）：公司债券（corporate bond）、商业票据
  第 4 档（Tier 4）：担保贷款、其他投资、加密资产

质量越高 = 压力情景下变现越快，盯市（mark-to-market）风险越低
```

**储备透明度层级（transparency hierarchy）：**
- 实时链上（on-chain）储备证明（proof of reserves）（最佳 — 加密资产支持的稳定币）
- 月度第三方鉴证（USDC 由 Deloitte 出具）
- 季度报告（Tether — 历史上因不透明而受到批评）
- 无验证（最差 — 应当回避）

### 脱锚风险因素

**系统性因素（systemic factor）：**
- 银行业危机（banking crisis）冲击稳定币储备托管人（custodian）（USDC/硅谷银行（SVB）：2023 年 3 月脱锚至 $0.87）
- 针对发行方的监管行动（regulatory action）（BUSD 被责令停止铸造）
- 智能合约（smart contract）漏洞利用（exploit）抽走储备
- 预言机操纵（oracle manipulation）引发连环清算（cascading liquidation）

**稳定币特有因素：**
- 储备构成恶化（degradation）（从短期国债转向风险更高的资产）
- 快速赎回流出超过流动性储备（liquid reserves）
- 储备托管中的交易对手风险（counterparty risk）
- 针对加密资产支持型稳定币的治理攻击
- 跨链（cross-chain）流动性碎片化（liquidity fragmentation）（桥接（bridged）USDC ≠ 原生（native）USDC）

### 历史脱锚事件

**UST/LUNA（2022 年 5 月）：**
- 触发因素：在 Curve 3pool 上对 UST 进行大规模协同卖出（$300M+）
- 机制失效：信心崩溃时，LUNA 的铸造/销毁制造出无限供给
- 脱锚深度：UST 从 $1.00 跌至 $0.02；LUNA 从 $80 跌至 $0.0001
- 损失：合计市值中约 $40 billion 被摧毁
- 教训：没有外生抵押品（exogenous collateral）的算法稳定币具有内在脆弱性

**USDC（2023 年 3 月）：**
- 触发因素：SVB 倒闭；Circle 把 $40B 储备中的 $3.3B 存放在 SVB
- 脱锚深度：去中心化交易所（DEX）上为 $0.87，中心化交易所（CEX）上为 $0.93
- 持续时间：2 天（周五晚间至周一上午，当时美联储（Fed）为存款提供了兜底（backstop））
- 恢复：美联储宣布银行定期融资计划（BTFP）并为存款提供担保之后，完全重新锚定（repeg）
- 教训：法币支持的稳定币承担银行体系风险；周末流动性缺口（liquidity gap）会放大脱锚

## 方法论

### 稳定币风险评估框架
1. **对锚定机制进行分类** — 法币支持、加密资产支持或算法型
2. **分析储备** — 构成、质量、透明度、托管
3. **评估赎回机制** — 多快能够拿回 $1？
4. **评估监管状态** — 是否持牌？哪个司法辖区（jurisdiction）？是否有待决的监管行动？
5. **检查链上流动性** — Curve/Uniswap 的资金池深度（pool depth），以及各条链上的 DEX 流动性
6. **监控市场信号** — Curve 资金池失衡（imbalance）、DEX 溢价（premium）/折价（discount）、资金费率（funding rate）
7. **评分并排序** — 在每个维度上赋予风险档位（risk tier）（1-5）

### 脱锚早期预警（early warning）指标
```
需要关注：
1. Curve 资金池失衡 >60/40（承压稳定币在资金池中成为主导）
2. 该稳定币在 CEX 的提现被暂停或延迟
3. 发行方对外沟通发生变化（延迟、含糊、领导层变动）
4. 折价持续 >0.5%，且持续时间达到 24 小时以上
5. 大规模赎回队列（加密资产支持型可在链上观察到）
6. 社交媒体情绪转向（恐惧、不确定与怀疑（FUD）可能变成自我实现（self-fulfilling））
7. 鉴证报告中的储备下降
8. 针对该发行方的监管公告
```

### 稳定币收益策略
```
低风险：
- 向 Aave/Compound 供给（年化收益率（APY）为浮动的 3-8%）
- Curve 3pool 流动性提供者（LP）（2-5% 基础收益 + CRV 奖励）
- DSR（MakerDAO 储蓄利率，目前为 5-15%，取决于治理）

中等风险：
- 在利率更高的较新协议上出借（智能合约风险更高）
- 在 DEX 上为波动（volatile）资产/稳定币交易对做 LP
- 以稳定币作为抵押品，进行 delta 中性（delta-neutral）基差交易（basis trading）

高风险：
- 在新链上参与奇异（exotic）稳定币挖矿（farm）
- 杠杆（leveraged）稳定币借贷循环（lending loop）
- 算法稳定币激励计划（incentive program）
```

## 示例

### 示例 1：USDC 脱锚交易（2023 年 3 月）
```
情境：SVB 的消息传出后，USDC 的交易价格为 $0.93
分析：
- Circle 的敞口（exposure）：$40B 储备中的 $3.3B（8.25%）
- 最坏情形：储备按 8.25% 减值（haircut）-> USDC 价值为 $0.9175
- 最好情形：存款得以追回 -> USDC 价值为 $1.00
- 价格为 $0.93 时的期望值（expected value）：若存款追回的可能性较大，则显著为正

交易：以 $0.93 买入 USDC
- 若存款被追回（概率 70%）：利润 = 7.5%
- 若适用减值（概率 30%）：亏损 = 1.4%
- 期望值：0.7 * 7.5% + 0.3 * (-1.4%) = 4.8%

结果：美联储为全部存款提供了兜底。USDC 在 48 小时内重新锚定。
2 天内回报 7.5%。
```

### 示例 2：Curve 资金池失衡预警
```
监控：Curve 3pool 的构成
正常状态：~33% DAI / ~33% USDC / ~33% USDT

检测到预警信号：
- DAI：25%
- USDC：25%
- USDT：50%

解读：市场正在把 USDT 抛售进该资金池，并买入 DAI/USDC。
这表明市场担心 USDT 的锚定或储备。
USDT 在 Curve 上的折价：0.2%

行动：
- 降低 USDT 敞口
- 监控 Tether 的赎回数据与储备鉴证
- 针对 USDT 失衡 >55% 设置警报（升级阈值，escalation threshold）
- 检查其他场所是否也出现折价（用以确认系统性担忧，还是该资金池特有的资金流）
```

### 示例 3：加密资产支持型稳定币压力测试（stress test）
```
DAI 压力测试情景：ETH 在 24 小时内下跌 40%

当前状态：
- DAI 总量：5B
- 由 ETH 支持的 DAI：2B（ETH 抵押品为 $4B，抵押率（CR）为 200%）
- 由 USDC 支持的 DAI：1.5B
- 由 RWA 支持的 DAI：1.5B

ETH 下跌 40% 之后：
- ETH 抵押品价值：$4B * 0.6 = $2.4B
- 抵押率：2.4B / 2B = 120%（低于 150% 阈值）
- 清算触发：约 $800M 的 ETH 金库被清算
- 清算罚金（liquidation penalty）产生收入，但可能连环蔓延
- 随着金库被关闭，DAI 供给收缩

评估：
- USDC 与 RWA 支持提供稳定下限（stability floor）（3B 支持 3B DAI = 100%）
- 若预言机保持在线，ETH 清算连环可以被控制住
- 关键风险：ETH 崩盘期间预言机失效，将使清算无法执行
- 由于抵押品分散，DAI 应当守住锚定
```

## 质量门禁（quality gate）

在依赖稳定币或投资于稳定币之前，请核实：

- [ ] 已理解锚定机制 — 它如何维持 $1？失效模式（failure mode）是什么？
- [ ] 已核实储备构成 — 已审阅近期鉴证或链上储备证明
- [ ] 已测试赎回机制 — 是否真的能够按 $1 赎回？延迟和最低额度是多少？
- [ ] 链上流动性充足 — 能否在不出现 >0.5% 滑点（slippage）的情况下退出你的头寸规模（position size）？
- [ ] 正在监控脱锚早期预警指标（Curve 资金池失衡、DEX 上的折价）
- [ ] 已识别交易对手风险 — 银行合作方、托管人、预言机提供方
- [ ] 监管状态清晰 — 发行方司法辖区、牌照、待决的监管行动
- [ ] 已审阅历史表现 — 该稳定币在 2023 年 3 月、2022 年 5 月期间的表现如何？
- [ ] 已管理集中度风险（concentration risk）— 不要把稳定币配置的 >50% 放在单一稳定币中
- [ ] 已考虑链特有风险 — 桥接 USDC 与原生 USDC、二层网络（L2）排序器（sequencer）依赖
