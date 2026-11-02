# 交易所规格核实与数据集清单 (Exchange-Verified Specs & Datasets)

核实日期：**2026-11-02**（所有规格均为当日现行值，非历史时点值；回测跨年使用时须注意下方"历史变动警示"）。

---

## 1. 数据集清单 (research/data/)

| 文件 | 行数 | 覆盖区间 (UTC) | 来源 | 用途 |
|---|---|---|---|---|
| `binance_um_btcusdt_perp_5m.csv` | 718,848 | 2019-12-31 00:00 → 2026-10-31 23:55 | data.binance.vision `futures/um/klines`（sha256 全部校验通过） | 成交价回测主序列（信号、VWAP、EMA、RSI、ATR） |
| `binance_um_btcusdt_perp_4h.csv` | 14,976 | 同上（仅完整 48×5m 的 4H） | 由 5m 重采样（锚点 00/04/08/12/16/20 UTC） | 上一根 4H 高/低突破轨道 |
| `binance_um_btcusdt_perp_mark_5m.csv` | 716,387 | 2019-12-23 11:55 → 2026-10-31 23:55 | data.binance.vision `futures/um/markPriceKlines`（sha256 全部校验通过） | **强平检查用标记价格** |
| `binance_um_btcusdt_perp_funding.csv` | 7,830 | 2019-09-10 08:00 → 2026-11-02 00:00 | Binance 官方 API `GET /fapi/v1/fundingRate` | 资金费现金流 |
| `nyse_sessions_2019_2027.csv` | 92 | 2019-12 → 2027-11 | `exchange_calendars` 4.5.6 XNYS 规则日历 + 手工补丁 | NYSE 全日休市 (77) 与提前收盘 (15, 13:00 ET) |
| `binance_api/*.json` | — | 2026-11-02 快照 | Binance fapi 公共端点原始返回 | 规格留档 |

### 数据缺口（已确认均为存档侧缺失，非脚本问题）

**成交价 5m**：仅缺 **2026-10-28** 整日（288 根）；2026-11-01 起的数据在拉取时点尚未发布。序列起点 2019-12-31 即存档最早日期（2019-09~11 存档未发布）。

**标记价格 5m** 缺口较多，强平检查需处理：

| 缺口 (UTC) | 缺根数 |
|---|---|
| 2020-12-17 07:30→07:55 | ~4 |
| 2021-06-30 23:55 → 07-02 00:00 | ~288（1 天） |
| **2021-07-23 23:55 → 07-28 00:00** | **~1152（4 天，最大缺口）** |
| 2022-07-30 → 08-01 | ~288 |
| 2022-10-01 → 10-03 | ~288 |
| 2023-02-23 → 02-25 | ~288 |
| 2023-11-10 03:35→04:05 | ~5 |
| 2026-06-28 → 06-30 | ~288 |
| 2026-10-27 23:55 → 10-30 00:00 | ~576（2 天） |

**资金费 CSV 注意**：时间戳存在毫秒级抖动（如 `...:00.001`），按交易所原始值保留；回测对齐时请先向下取整到整点。已验证全部 7,830 个事件均落在 00/08/16 UTC 三个时隙。

**零成交量 5m K 线**：66 根（0.009%），集中在 8 个日期（如 2023-11-10×19、2024-10-28×16）。回测须对 VWAP 除零设防，并跳过这些 K 线上的进出场判定。

---

## 2. Binance USDⓈ-M BTCUSDT 永续合约规格（已核实）

### 2.1 合约与精度（来源：`GET /fapi/v1/exchangeInfo?symbol=BTCUSDT`，2026-11-02 快照）

| 项 | 值 |
|---|---|
| 合约类型 | PERPETUAL（USDT 保证金，币对 BTC/USDT） |
| 价格精度 tickSize | **0.10** |
| 数量精度 stepSize | **0.001** BTC（最小下单 0.001） |
| 最小名义价值 | 50 USDT（MIN_NOTIONAL，现行值；历史上调整过） |

### 2.2 资金费（Funding）

*来源：[Introduction to Binance Futures Funding Rates](https://www.binance.com/en/support/faq/detail/360033525031)、`GET /fapi/v1/fundingInfo`（快照）、`GET /fapi/v1/fundingRate` 全历史*

- **间隔：每 8 小时，00:00 / 08:00 / 16:00 UTC**。已从交易所全量历史（7,830 个事件）实证：BTCUSDT 自始至终全部落在该三时隙，无 4h/1h 动态调整记录。仅在持仓跨过资金费时点时才收/付。
- **公式**（2025-09-18 08:01 UTC 起现行）：

  F = [ AveragePremiumIndex(P) + clamp(利率 − P, +0.05%, −0.05%) ] / (8/N)，N = 资金费间隔小时数

  2025-09-18 之前：F = P + clamp(每期间利率 − P, +0.05%, −0.05%)（无 ÷(8/N) 缩放；对 8h 间隔两者等价，BTCUSDT 一直为 8h，故历史口径一致）。
- **利率**：默认每日 0.03%（8h 制下每期 **0.01%**；`premiumIndex` 快照 interestRate=0.0001 ✓）。Premium Index ∈ [−0.04%, 0.06%] 时资金费=利率 0.01%。
- **上下限**（fundingInfo 快照）：adjustedFundingRateCap/Floor = **±0.30%**（= 0.75 × 第 1 档维持保证金率 0.40%）。
- Premium Index P = [max(0, 冲击买价 − 价格指数) − max(0, 价格指数 − 冲击卖价)] / 价格指数。

### 2.3 标记价格（Mark Price）

*来源：[What Are Mark Price and Price Index in USDⓈ-M Futures](https://www.binance.com/en/support/faq/detail/360033525071)、[2025-09-18 公式调整公告](https://www.binance.com/en/square/post/29758472068434)*

- **Mark Price = Median(Price 1, Price 2, 合约最新价)**
- Price 1 = 价格指数 × (1 + 最近资金费率 × 距下次资金费时间/资金费周期)
- Price 2 = 价格指数 + 基差移动平均，基差 = (买一+卖一)/2 − 价格指数
  - **2025-09-18 起：30 秒窗口（30 个 1 秒采样）**；之前为 **1 分钟窗口（60 个采样）**。
  - ⚠️ 历史 markPriceKlines 在 2025-09-18 前后由略有差异的 Price 2 窗口生成；对 5m 粒度强平检查影响极小，但属口径变动，特此留档。
- 价格指数 = 多家主流现货交易所价格的加权复合（权重由 Binance 定期调整）。
- 极端行情下 Binance 保护性措施：可直接采用 Mark Price = Price 2；剧烈波动时可把合约置为 reduce-only。
- **强平以标记价格触发，非最新成交价** — 回测中强平检查必须使用 `..._mark_5m.csv`。

### 2.4 维持保证金（Maintenance Margin）

*来源：[Leverage and Margin of USDⓈ-M Futures](https://www.binance.info/en/support/faq/detail/360033162192)、[Leverage & Margin 档位表](https://www.binance.com/en/futures/trading-rules/perpetual/leverage-margin)（BTCUSDT 档位最近更新 2025-08-19）*

**维持保证金 = 持仓名义价值 × 维持保证金率(MMR) − 维持保证金速算额(cum)**

现行 BTCUSDT 档位（前 6/12 档，2026-10 末读取）：

| 档 | 名义价值上限 (USDT) | 最高杠杆 | MMR | cum (USDT) |
|---|---|---|---|---|
| 1 | 300,000 | 150x | 0.40% | 0 |
| 2 | 800,000 | 100x | 0.50% | 300 |
| 3 | 3,000,000 | 75x | 0.65% | 1,500 |
| 4 | 12,000,000 | 50x | 1.00% | 12,000 |
| 5 | 70,000,000 | 25x | 2.00% | 132,000 |
| 6 | 100,000,000 | 20x | 2.50% | 482,000 |

- MMR <0.5% 的调整可能不另行公告；新开户前 30 天全品种杠杆上限 20x（2025-12-07 起）。
- ⚠️ **历史变动警示**：档位与最高杠杆多次调整（上线初期 20x→后续 100x/125x→现行 150x；2021-07 起新用户 20x 限制等）。本表为现行值；回测早期年份做强平检查属近似（本策略仓位规模远小于第 1 档上限时，MMR=0.40%、cum=0 在各历史时期基本稳定，影响可控）。

### 2.5 手续费（Trading Fees）

*来源：[USDⓈ-M Futures Trading Fee Rate](https://www.binance.com/en/fee/futureFee)、[Fee Structure FAQ](https://www.binance.info/en/support/faq/detail/360033544231)*

| 级别 | USDT 合约 Maker / Taker | BNB 支付 9 折 |
|---|---|---|
| **Regular (VIP 0)** | **0.0200% / 0.0500%** | 0.0180% / 0.0450% |
| VIP 1 | 0.0180% / 0.0500% | … |
| VIP 2 | 0.0160% / 0.0400% | … |

- 手续费 = 成交名义价值 × 费率；市价单（本策略"下一根 K 线开盘价进场"）按 **taker** 计。
- 另有 U 本位永续促销活动（0 maker + taker 折扣，限期）与 Taker Program 返佣（按周考核），回测不计。
- ⚠️ **历史变动警示**：费率表并非恒定——2026-03-19 的 VIP 调整将 VIP1/2 taker 由 0.04%/0.035% 上调至 0.05%/0.04%（[公告](https://www.binance.info/en/support/announcement/detail/4f379b9ab6314eff8fe02babfe255825)）。更早年份 VIP0 taker 曾低于 0.05%。**回测建议按现行 0.05% taker 常数计，属保守上界**（与 okx_btc_swap_backtest.py 的处理口径一致）。
- 强平成交另收 **Insurance Clearance Fee**（保险清算费），爆仓情景才涉及。

### 2.6 强平价格公式（Liquidation Price）

*来源：[How to Calculate Liquidation Price of USDⓈ-M Futures Contracts](https://www.binance.com/en/support/faq/detail/b3c689c1f50a44cabb3a84e663b81d93)、[Liquidation Protocols](https://www.binance.com/en/support/faq/binance-futures-liquidation-protocols-360033525271)*

- 触发条件：**抵押品 = 初始抵押 + 已实现盈亏 + 未实现盈亏（按标记价格计） < 维持保证金**，即**标记价格触及强平价**。
- 逐仓（isolated）、单向持仓（one-way），TMM=0、UPNL=0：

  **LP = (WB + cum − side × Q × EP) / (Q × MMR − side × Q)**

  - 多单 side=+1：LP = (WB + cum − Q×EP) / (Q × (MMR − 1))
  - 空单 side=−1：LP = (WB + cum + Q×EP) / (Q × (MMR + 1))
  - WB = 逐仓钱包余额（初始保证金 ± 已加/减保证金），Q = 仓位数量，EP = 开仓均价。
- ⚠️ 档位一致性：若算出的 LP 使名义价值落入其他档位，须用该档 MMR/cum 重算。
- 回测口径：每根 5m K 线用**标记价格 high/low** 与 LP 比较；标记序列缺口区间（见 §1）退化为成交价近似并打标，或跳过该区间强平判定。

---

## 3. NYSE 假日与提前收盘日历（有来源）

- 文件：`nyse_sessions_2019_2027.csv`，92 行 = 77 全日休市 + 15 提前收盘（均 **13:00 ET**）。
- 主来源：`exchange_calendars` 4.5.6 的 XNYS 规则日历（编码 NYSE 法定假日规则、特殊提前收盘规则，含 Juneteenth 2022 起等）。交叉核对：[NYSE Hours & Calendars](https://www.nyse.com/markets/hours-calendars)。
- 手工补丁：**2025-01-09 Jimmy Carter 全国哀悼日全日休市**（包内临时休市表未收录；依 NYSE 2024-12-30 公告补入，脚本 `nyse_calendar_export.py` 中 `FORCED_ADHOC_CLOSURES`）。
- 常规提前收盘：感恩节次日（Black Friday）、12-24 Christmas Eve、独立日前特定工作日（如 2025-07-03），均 13:00 ET 收盘。
- 覆盖 2019-12 → 2027-11（`exchange_calendars` 日历上界）；更远日期需升级包后重跑 `nyse_calendar_export.py`。

---

## 4. 回测落地要点

1. **信号/成交用成交价 5m，强平判定用标记价格 5m** — 两条序列按 open_time 对齐；交集起点 2019-12-31。
2. 资金费按持仓是否跨过 00/08/16 UTC 时点收付；对齐时把 funding 时间戳毫秒抖动向下取整到整点。
3. 缺口处理：成交价序列仅缺 2026-10-28；标记序列缺口见 §1 表，缺口内强平检查降级（成交价近似 + 打标）或跳过并计数。
4. 66 根零量 K 线：跳过信号与成交，VWAP 计算防除零。
5. 费用口径：taker 0.05% 常数（保守上界）、资金费按历史实际值、强平仅在标记价格触发时计（附保险清算费提示）。
6. 所有规格为 2026-11-02 现行值；跨年回测属近似，§2 各"历史变动警示"即偏差来源。
