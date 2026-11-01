## 突破動量策略（Breakout & Momentum Strategy）

### 1. 核心邏輯（Why it works）

BTC 在 5m / 15m 的短線走勢中，約有 70% 的時間處於窄幅震盪，30% 的時間會在瞬間發動爆發性單邊行情。

* **突破爆發**：當價格強勢打破過去一段時間的價格箱體（整理區間）時，會大量觸發空頭止損或多頭追單，形成**短時間內的極速推進**。
* **20x 槓桿優勢**：20 倍槓桿不需要抓住大波段，只需捕捉突破後 **0.5% ~ 1.5% 的極短線順勢衝擊**，就能獲得 10% ~ 30% 的本金收益。

---

### 2. 技術指標與參數設定

* **主時間軸**：5 分鐘 K 線（5m）或 15 分鐘 K 線（15m）。
* **唐奇安通道（Donchian Channel, 20 週期）**：用來實時定義過去 20 根 K 線的最高價與最低價（即短線整理箱體）。
* **成交量過濾（Volume Filter）**：當前突破 K 線的成交量必須高於 **過去 20 週期平均成交量的 1.5 倍**（無量突破多為假突破）。
* **大週期方向過濾（EMA 200 Trend Filter）**：參考 1 小時（1h）K 線的 200 EMA：
* 當 1h 價格在 200 EMA **之上** ➔ **只做多（Long Only）**。
* 當 1h 價格在 200 EMA **之下** ➔ **只做空（Short Only）**。



---

### 3. 進出場與風控規則（20x 槓桿極致風控）

| 動作 | 執行條件 | 20x 槓桿實施細節 |
| --- | --- | --- |
| **開倉條件（Entry）** | 5m K 線收盤價向上突破 20 週期最高價（或向下跌破最低價），且成交量放大，符合大週期 EMA 方向。 | 必須採用 **Post-Only / Maker 限價單** 或精準 Trigger 觸發，避免市價單滑點吞噬利潤。 |
| **硬止損（Stop-Loss）** | **固定設在 0.6% ~ 0.8% 價格距離**（或前一根 5m K 線的高/低點外側）。 | 價格逆轉 0.8% 乘以 20 倍槓桿 = **本金硬止損約 16%**。切記：**必須使用逐倉模式（Isolated Margin）**。 |
| **止盈與移動止損（TP / Trailing）** | **第一目標（0.8%）**：平倉 50% 鎖定利潤。<br>

<br>**剩餘 50%**：啟動動態移動止損（Trailing Stop），當價格回撤 0.3% 時全數離場。 | 確保風報比（Risk-to-Reward Ratio）維持在 **1 : 1.5 至 1 : 2** 以上。 |

---

### 4. 20x 槓桿下的 Python 量化偽代碼範例

在 Hyperliquid 等平台上，量化腳本的下單與硬止損邏輯示意如下：

```python
import pandas as pd

def breakout_strategy_5m(df_5m, df_1h):
    # 1. 計算大趨勢過濾器 (1h EMA 200)
    df_1h['ema200'] = df_1h['close'].ewm(span=200, adjust=False).mean()
    trend_long = df_5m['close'].iloc[-1] > df_1h['ema200'].iloc[-1]
    
    # 2. 計算 5m 唐奇安通道與成交量均線
    df_5m['donchian_high'] = df_5m['high'].shift(1).rolling(window=20).max()
    df_5m['donchian_low'] = df_5m['low'].shift(1).rolling(window=20).min()
    df_5m['vol_ma20'] = df_5m['volume'].rolling(window=20).mean()
    
    current_close = df_5m['close'].iloc[-1]
    current_vol = df_5m['volume'].iloc[-1]
    donchian_h = df_5m['donchian_high'].iloc[-1]
    vol_ma = df_5m['vol_ma20'].iloc[-1]
    
    # 3. 判斷多頭突破進場訊號
    if trend_long and (current_close > donchian_h) and (current_vol > 1.5 * vol_ma):
        entry_price = current_close
        # 20x 槓桿下，0.7% 的價格移動即觸發止損
        stop_loss_price = entry_price * (1 - 0.007)
        take_profit_price = entry_price * (1 + 0.014) # 1:2 風報比
        
        return {
            "action": "BUY",
            "leverage": 20,
            "margin_mode": "ISOLATED", # 必須使用逐倉模式
            "entry_price": entry_price,
            "stop_loss": stop_loss_price,
            "take_profit": take_profit_price
        }
    
    return {"action": "HOLD"}

```

---

### 💡 執行「一號策略」的致命注意事項

1. **手續費侵蝕（Fee Erosion）**：
在 20 倍槓桿下，交易所收取名義價值的 0.04% Taker 手續費，折合**佔用你保證金本金的 0.8%**（一進一出即吃掉 1.6% 本金）。策略必須儘量使用 **Maker (掛單)** 進場。
2. **避開重大數據公佈時段**：
美聯儲 CPI、FOMC 利率決議公佈前後 15 分鐘內，5m K 線會出現劇烈雙向插針，20x 槓桿極易造成「多空雙爆」，量化程式在新聞發布時段應強制關閉交易。