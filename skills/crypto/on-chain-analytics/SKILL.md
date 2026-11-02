# 链上分析（On-Chain Analytics）

## 何时启用
- 分析区块链数据（blockchain data）以获取交易信号（trading signal）（巨鲸（whale）动向、交易所资金流（exchange flows）、网络健康度（network health））
- 使用链上指标（on-chain metrics）评估加密资产（crypto asset）基本面（fundamentals）
- 构建或解读来自 Glassnode、Nansen、Dune Analytics 或同类平台的仪表盘（dashboard）
- 通过钱包聚类（wallet clustering）与实体行为（entity behavior）评估市场结构（market structure）

## 核心概念

### 区块链数据分层
1. **原始交易数据（raw transaction data）** — 输入（input）、输出（output）、gas、时间戳（timestamp）、合约交互（contract interaction）
2. **派生指标（derived metrics）** — 由原始数据计算得到的汇总统计（活跃地址（active addresses）、转账量（transfer volume））
3. **实体级分析（entity-level analytics）** — 将地址聚类为钱包，并为交易所、基金、巨鲸打上标签
4. **行为信号（behavioral signal）** — 将实体行动解读为看涨（bullish）/看跌（bearish）指标

### 关键链上指标

**供给指标（Supply Metrics）：**
- **流通供给（circulating supply）** — 在回看窗口（lookback window）内发生过移动的代币（例如 1 年）
- **已实现市值（realized cap）** — 每个未花费交易输出（UTXO）按其上次移动时的价格估值后求和；平滑投机溢价（speculative premium）
- **MVRV 比率（MVRV ratio）** — 市值（Market Value）/ 已实现价值（Realized Value）；历史上高于 3.5 预示过热（overheating），低于 1.0 预示深度价值（deep value）
- **NUPL**（净未实现盈亏（Net Unrealized Profit/Loss）） — 全体持有者的未实现收益合计；>0.75 = 狂热（euphoria），<0 = 投降（capitulation）

**网络活动（Network Activity）：**
- **活跃地址** — 每日唯一的发送/接收地址；作为网络采用（network adoption）的代理
- **交易笔数与交易量（transaction count and volume）** — 原始吞吐量（throughput）；区分经济转账与垃圾交易（spam）/自转账（self-transfer）
- **NVT 比率**（网络价值与交易量之比（Network Value to Transactions）） — 市值 / 每日链上转账量；相当于加密资产的市盈率（P/E ratio）
- **NVT 信号（NVT Signal）** — 使用转账量的 90 日移动平均（MA），以得到更平滑的信号；对 BTC 而言，历史上 >150 表示高估（overvalued）

**挖矿/质押（Mining/Staking）：**
- **算力（hash rate）** — 保障工作量证明（PoW）网络的总计算能力；持续下降预示矿工投降（miner capitulation）
- **算力缎带（hash ribbons）** — 算力的 30 日移动平均下穿 60 日移动平均；缎带修复时，历史上是强劲的买入信号
- **质押比率（staking ratio）** — 供给中被质押的百分比；比率较高会减少流动供给（liquid supply），但也可能表示自满（complacency）

### 交易所资金流分析

**流入/流出框架（Inflow/Outflow Framework）：**
- **交易所流入（exchange inflow）** — 代币转入交易所钱包；预示潜在卖压（selling pressure）
- **交易所流出（exchange outflow）** — 代币离开交易所；预示积累（accumulation）/冷存储（cold storage）
- **净流量（net flow）** — 流入减去流出；持续为负的净流量在结构上看涨
- **交易所储备（exchange reserve）** — 交易所持有的代币总量；储备下降会减少可用的卖方流动性（sell-side liquidity）

**巨鲸追踪（whale tracking）：**
- 按资产定义巨鲸阈值（BTC：>1000 BTC，ETH：>10,000 ETH）
- 将巨鲸到交易所的转账作为潜在派发（distribution）信号加以追踪
- 监控巨鲸积累地址（交易所到巨鲸的资金流）
- Nansen 的 "Smart Money" 标签追踪历史上具有盈利行为的钱包

### 钱包聚类与实体分析

**聚类方法（Clustering Methods）：**
- **共同输入启发式（common input heuristic）** — 在同一笔交易中作为输入使用的地址，很可能属于同一实体
- **找零地址识别（change address detection）** — 识别找零输出，以便与发送地址归为一组
- **时序分析（timing analysis）** — 持续一起发生交易的地址
- **合约交互模式（contract interaction pattern）** — 以相似模式与相同去中心化金融（DeFi）协议交互的钱包

**实体类别（Entity Categories）：**
- 交易所（由 Chainalysis、Nansen、Arkham 打标）
- 矿池与矿工
- DeFi 协议及其金库（treasury）
- 机构托管方（institutional custodian）
- 已知基金钱包（a16z、Paradigm 等）

## 方法论

### 信号构建流程（Signal Construction Process）
1. **数据接入（data ingestion）** — 从节点、索引器（indexer，The Graph）或分析 API 拉取原始数据
2. **指标计算（metric computation）** — 用适当的回看窗口计算派生指标
3. **标准化（normalization）** — 对照历史分布，对指标做 z 分数（z-score）或百分位排名（percentile rank）
4. **信号生成（signal generation）** — 为可执行信号定义阈值或状态边界（regime boundary）
5. **共振（confluence）** — 组合多个链上信号；高确信度（high conviction）要求 3+ 次确认

### 实务分析工作流（Practical Analysis Workflow）
```
步骤 1：检查交易所净流量（代币是否正在离开交易所？）
步骤 2：审视 MVRV 与 NUPL（当前处于高估区间还是低估（undervalued）区间？）
步骤 3：检视活跃地址趋势（采用是在增长还是在收缩？）
步骤 4：监控巨鲸行为（是在积累还是在派发？）
步骤 5：与资金费率（funding rate）及衍生品（derivatives）数据交叉验证
步骤 6：综合为带有置信水平（confidence level）的方向性偏向（directional bias）
```

### 数据源层级（Data Source Hierarchy）
- **第一级（Tier 1，最可靠）：** 运行自己的全节点（full node），解析原始区块
- **第二级（Tier 2）：** 索引数据提供商（The Graph、Bitquery、Flipside）
- **第三级（Tier 3）：** 分析平台（Glassnode、Nansen、CryptoQuant、IntoTheBlock）
- **第四级（Tier 4）：** 社交/聚合仪表盘（Dune 社区查询、DefiLlama）

## 示例

### 示例 1：BTC 积累信号
```
观察：
- 交易所储备连续下降 30+ 天
- MVRV 为 0.85（低于已实现价值）
- 巨鲸地址（>1000 BTC）数量增加
- 算力缎带在矿工投降之后修复

评估：强积累阶段。多项链上指标与历史上的熊市底部（bear market bottom）
相一致。高确信度的做多偏向（long bias）。
```

### 示例 2：ETH 派发预警
```
观察：
- 来自前 100 大钱包的大额交易所流入（连续 3 天）
- NVT 信号为 180（历史上的高估区间）
- NUPL 为 0.72（接近狂热）
- 尽管价格上涨，新地址增长趋于平缓

评估：派发信号正在出现。价格上涨没有得到网络增长的支持。
缩小仓位规模（position size），收紧止损（stop）。
```

### 示例 3：稳定币（stablecoin）供给扩张
```
观察：
- USDT 与 USDC 合计市值在 7 天内增加 $2B
- 稳定币交易所储备上升（干火药（dry powder）正在积累）
- 稳定币主导地位（stablecoin dominance）从近期高点回落

评估：资本经由稳定币流入加密生态系统（crypto ecosystem）。
历史上先于风险偏好行情（risk-on rally）。关注向
BTC/ETH 的部署，作为确认。
```

## 质量门禁（Quality Gate）

在依据链上信号采取行动之前，核实：

- [ ] 数据源可靠且为最新（检查索引延迟（indexing lag），通常为 1-6 个区块）
- [ ] 指标使用适当的回看窗口计算（避免近因偏差（recency bias））
- [ ] 巨鲸动向已在多个追踪平台上得到确认（避免错误标签（false label））
- [ ] 交易所资金流数据已计入内部转账（internal transfer）与钱包轮换（wallet rotation）（交易所会定期重新调配热钱包（hot wallet）/冷钱包（cold wallet））
- [ ] 链上信号至少得到另一个数据领域的佐证（衍生品、情绪（sentiment）或价格行为（price action））
- [ ] 已考虑背景因素 — 协议升级（protocol upgrade）、空投（airdrop）与跨链桥（bridge）活动可能扭曲链上指标
- [ ] 时间范围（time horizon）与信号频率相匹配 — 链上指标通常是中期（数周至数月），而非日内（intraday）
- [ ] 计入链特有的细微差异 — UTXO 对比账户模型（account model），一层（L1）对比二层（L2）活动
