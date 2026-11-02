# 最大可提取价值（MEV）策略

## 何时启用
- 分析去中心化金融（DeFi）交易中的 MEV 机会或风险
- 理解抢跑（frontrunning）、三明治攻击（sandwich attack），以及去中心化交易所（DEX）套利（arbitrage）的机制
- 评估 MEV 缓解策略（Flashbots、MEV-boost、私有内存池（private mempool））
- 设计交易，以便把 MEV 提取降到最低，或参与 MEV 捕获
- 评估提议者-构建者分离（proposer-builder separation, PBS）及其对协议设计的影响

## 核心概念

### MEV 分类

**定义：** MEV 是在标准区块奖励和 gas 费用之外，通过在一个区块内纳入、排除或重新排序交易，能够从区块生产中提取的最大价值。

**主要 MEV 类型：**

1. **DEX 套利**——利用不同 DEX 之间，或不同 DEX 资金池之间的价差
   - 原子（atomic）：借助闪电贷（flash loan），在单笔交易内执行
   - 跨 DEX（cross-DEX）：Uniswap 资金池的价格不同于 SushiSwap
   - 跨资金池（cross-pool）：在 3+ 个资金池之间做三角套利（triangular arbitrage）（ETH->USDC->DAI->ETH）
   - 按体量估计，占全部 MEV 的 60-70%

2. **三明治攻击**——对受害者的兑换（swap）进行抢跑和尾随（backrunning）
   - 攻击者在内存池（mempool）中看到待处理的兑换
   - 抢跑：在受害者之前买入该代币，从而推高价格
   - 受害者的兑换以更差的价格成交
   - 尾随：在受害者之后以更高的价格卖出该代币
   - 利润 = 所制造的价格冲击（price impact）减去 gas 成本
   - 受害者的损失：其有效滑点（effective slippage）超过预期滑点（expected slippage）

3. **清算 MEV（liquidation MEV）**——竞相清算抵押不足（undercollateralized）的仓位
   - 监控 Aave、Compound、MakerDAO 上的健康因子（health factor）
   - 最先调用 liquidate() 的一方捕获清算奖励（liquidation bonus）（5-10%）
   - 相互竞争的清算机器人之间进行 gas 优先费拍卖（gas priority auction）
   - 闪电贷使清算无需预付本金即可进行

4. **非同质化代币（NFT）MEV**——狙击定价偏低的挂单，并对铸造（mint）进行抢跑
   - 系统性较低，更多由事件驱动（event-driven）
   - 在热门发行期间进行铸造狙击（mint sniping）

5. **长尾 MEV（long-tail MEV）**——针对特定协议的提取（治理、预言机操纵（oracle manipulation））

### 三明治攻击机制（详解）

```
内存池状态：受害者要在 Uniswap 上将 10 ETH 兑换为 USDC
资金池状态：1000 ETH / 2,000,000 USDC（价格 = 2000 USDC/ETH）
受害者的滑点容忍度（slippage tolerance）：1%

攻击者抢跑：
- 用 50 ETH 买入 -> 获得 ~95,238 USDC
- 新资金池：1050 ETH / 1,904,762 USDC（价格 = 1814 USDC/ETH）

受害者的兑换成交：
- 10 ETH -> 获得 ~17,878 USDC（对比无三明治攻击时的 ~19,802）
- 受害者损失 ~$1,924

攻击者尾随：
- 卖出 95,238 USDC -> 获得 ~51.8 ETH
- 利润：~1.8 ETH 减去 gas 成本（~0.1 ETH）
- 提取到的净 MEV：~1.7 ETH（$3,400）
```

### Flashbots 与 MEV 基础设施

**Flashbots 生态系统：**
- **Flashbots Protect**——私密交易提交（private transaction submission），绕过公开内存池（public mempool）
- **Flashbots Auction (MEV-Auction)**——搜索者（searcher）为交易包（bundle）被纳入而出价
- **MEV-boost**——面向 Ethereum 的协议外（out-of-protocol）PBS 实现
- **MEV-Share**——把 MEV 重新分配给发起这些交易的用户

**MEV-Boost 架构：**
```
交易流：
用户 -> 内存池 -> 搜索者（发现 MEV）-> 构建者（builder）（构建区块）
  -> 中继（relay）（验证区块）-> 提议者（proposer）（选择出价最高的区块）

关键角色：
- 搜索者：发现 MEV 机会，创建交易包
- 构建者：把交易包聚合成完整区块，并为被纳入而出价
- 中继：验证构建者区块的受信任中介（trusted intermediary）
- 提议者：选择胜出区块的验证者（validator）
```

**提议者-构建者分离（PBS）：**
- 把区块构建（选择/排序交易）与区块提议（验证）分开
- 防止验证者直接提取 MEV
- 形成竞争性的区块构建市场
- 内嵌 PBS（enshrined PBS）：协议层实现（位于 Ethereum 路线图中）
- 当前的 MEV-boost 是协议外的受信任中继（trusted relay）模式

### MEV 缓解策略

**对用户：**
- 使用 Flashbots Protect 或 MEV-blocker 进行私密交易提交
- 把滑点容忍度设得较紧（但不要紧到使交易失败）
- 在可行时使用限价单（limit order），替代市价兑换（market swap）
- 借助时间加权平均价格（time-weighted average price, TWAP），把大额交易拆成较小的多笔
- 使用经由私有池（private pool）路由的 DEX 聚合器（DEX aggregator）（CoW Swap、1inch Fusion）

**对协议：**
- **批量拍卖（batch auction）**——CoW Protocol：同一批次中的全部交易以统一出清价格（uniform clearing price）结算
- **加密内存池（encrypted mempool）**——阈值加密（threshold encryption）、承诺-揭示方案（commit-reveal scheme）
- **公平排序（fair ordering）**——Chainlink FSS（公平排序服务，Fair Sequencing Services）
- **MEV 再分配（MEV redistribution）**——MEV-Share、协议自有的 MEV 捕获（protocol-owned MEV capture）
- **时间加权平均定价（time-weighted average pricing）**——降低单区块操纵
- **仅尾随拍卖（backrunning-only auction）**——允许有益的套利，阻止有害的抢跑

## 方法论

### MEV 机会评估
1. **识别 MEV 类型**——套利、清算、三明治攻击，或针对特定协议
2. **估计毛收入（gross revenue）**——价差（price discrepancy）* 交易规模，清算奖励 * 仓位规模
3. **计算成本**——gas 成本、优先费（priority fee）/出价（bid）、闪电贷费用、资金成本（capital cost）
4. **评估竞争**——还有多少其他搜索者在针对这一机会？利润率会随竞争而收窄
5. **评估风险**——失败的交易会消耗 gas，存在智能合约风险（smart contract risk），非原子（non-atomic）策略还有库存风险（inventory risk）
6. **确定基础设施**——延迟要求、与构建者的关系、私有内存池访问

### 搜索者盈利能力分析
```
每个机会的期望利润：
E[profit] = P(win_auction) * (gross_MEV - gas - bid) - P(lose_auction) * wasted_gas

其中：
- P(win_auction) 会随更多搜索者参与竞争而下降
- bid 在竞争性市场中向 gross_MEV 收敛
- wasted_gas = 失败或回滚交易的成本
- 成熟的 MEV 类型（DEX 套利）利润率很薄；新颖类型的利润空间很宽
```

### 面向 DeFi 用户的 MEV 风险评估
```
1. 估计交易规模相对于资金池流动性的比例
2. 计算不存在 MEV 时的预期价格冲击
3. 加上 MEV 提取估计（通常为可得三明治利润的 20-80%）
4. 比较总执行成本与使用私密交易通道时的成本
5. 对于大额交易：评估 TWAP、询价（request for quote, RFQ）或批量拍卖等替代方案
```

## 示例

### 示例 1：原子 DEX 套利
```
机会：
- Uniswap ETH/USDC 资金池：ETH 价格 = $2,010
- SushiSwap ETH/USDC 资金池：ETH 价格 = $2,000
- 价差：每 ETH $10

执行：
1. 从 Aave 闪电贷 100 ETH
2. 在 Uniswap 以 $2,010 卖出 100 ETH = $201,000
3. 在 SushiSwap 用 $201,000 买入 ~100.5 ETH
4. 偿还 100 ETH 闪电贷 + 0.05 ETH 费用
5. 利润：0.45 ETH（~$900）减去 gas 与构建者小费（builder tip）

交易包提交：
- 通过 Flashbots 提交，以避免暴露在内存池中
- 向构建者出价利润的 60%（$540），以确保被纳入
- 净利润：每个机会 ~$360
```

### 示例 2：清算机器人策略
```
监控：
- 持续跟踪 10,000+ 个 Aave 仓位
- 为每个仓位预先计算清算价格
- 订阅待处理区块头（pending block header），以获取价格更新

当仓位变为可清算（liquidatable）时的执行：
- 健康因子降至 1.0 以下
- 闪电贷借入债务资产（debt asset）
- 调用 liquidate()，偿还债务，收到抵押品（collateral）+ 奖励
- 把抵押品兑换回债务资产
- 偿还闪电贷

经济性：
- 平均清算奖励：5%
- 平均清算规模：$50,000
- 毛利润（gross profit）：$2,500
- Gas + 构建者小费：$500-1,000
- 净利润：每次清算 $1,500-2,000
- 竞争：高，对延迟敏感（亚区块时序（sub-block timing））
```

### 示例 3：MEV 保护对比
```
交易：把 50 ETH 兑换为 USDC

路径 1 — 公开内存池（直接使用 Uniswap）：
- 预期输出：99,500 USDC
- 三明治提取：-$800（估计值）
- 实际输出：~98,700 USDC

路径 2 — Flashbots Protect：
- 预期输出：99,500 USDC
- 无法进行三明治攻击（私密提交）
- 实际输出：~99,400 USDC（仅为正常滑点）

路径 3 — CoW Swap（批量拍卖）：
- 预期输出：99,600 USDC（来自批量匹配的盈余（surplus））
- 无 MEV 提取 + 可能的价格改善（price improvement）
- 实际输出：~99,550 USDC

建议：对于 >$10K 的交易，始终使用 MEV 保护。
CoW Swap 为大额稳定币（stablecoin）兑换提供最佳执行（best execution）。
```

## 质量关卡

在着手 MEV 策略或评估 MEV 风险之前，核实：

- [ ] MEV 类型识别正确——套利是建设性的（改善定价），三明治攻击是提取性的
- [ ] 全部成本都已计入——gas、优先费、构建者出价、闪电贷费用、失败交易的成本
- [ ] 已评估竞争程度——成熟的 MEV 类型利润极薄，对新进入者而言期望值（expected value, EV）常常为负
- [ ] 智能合约交互已经过审计——闪电贷回调（flash loan callback）和复杂的多跳兑换（multi-hop swap）带有漏洞利用风险（exploit risk）
- [ ] 已注明监管方面的考量——部分 MEV 活动可能面临法律审查（尤其是三明治攻击）
- [ ] 基础设施要求符合实际——亚秒级延迟、专门的构建者关系、定制节点配置
- [ ] 面向用户的 MEV 保护建议与其交易规模和交易频率相匹配
- [ ] 对 PBS 架构的理解保持最新——MEV 供应链（MEV supply chain）演变迅速
- [ ] 已考虑跨链 MEV（cross-chain MEV）——跨链桥（bridge）和二层网络（layer 2, L2）排序器（sequencer）会引入新的 MEV 动态
