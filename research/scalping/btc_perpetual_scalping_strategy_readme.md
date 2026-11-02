# BTC Perpetual Intraday Scalping Strategy (5x Leverage)

A high-probability, momentum-and-trend-following quant trading strategy designed for **BTC/USDT Perpetual Contracts** on intraday timeframes (**5-Minute / 5m**). 

The strategy utilizes a multi-layered filtering process combining **EMA (Trend)**, **VWAP (Institutional Value)**, **MACD (Momentum)**, and **RSI (Oscillator Filter)** with a calibrated **5x Leverage** setup to optimize capital efficiency while minimizing noise liquidation.

---

## 📋 Strategy Overview

* **Asset Class:** Crypto Derivatives (BTCUSDT Perpetual Swap)
* **Execution Timeframe:** 5-Min (5m) K-Line Charts
* **Trend Confirmation Timeframe:** 15-Min / 1-Hour
* **Core Style:** Intraday Trend-Following & Momentum Breakout Scalping
* **Leverage Level:** **5x (Isolated Margin)**
* **Target Risk/Reward Ratio:** 1 : 1.5 to 1 : 2.0
* **Average Hold Time:** 15 minutes – 2 hours

---

## ⚙️ Indicator Configuration

| Indicator | Setting | Purpose / Role |
| :--- | :--- | :--- |
| **EMA Fast** | 20 Periods | Dynamic micro-trend support/resistance |
| **EMA Slow** | 50 Periods | Baseline intraday directional trend filter |
| **VWAP** | Daily Cumulative | Institutional benchmark (fair market value zone) |
| **MACD** | Fast: 12, Slow: 26, Signal: 9 | Momentum confirmation & entry trigger |
| **RSI** | 14 Periods | Overbought/Oversold filter to prevent chasing |
| **ATR** | 14 Periods | Volatility-based dynamic stop-loss positioning |

---

## 🚦 Trading Logic & Rules

### 1. Long Entry Conditions (BUY / CALL)
All conditions must be satisfied on a **closed 5m candle**:

1. **Trend Filter:** Price > **EMA 20** > **EMA 50** AND Price > **VWAP**.
2. **Momentum Signal:** MACD Line > Signal Line (or bullish crossover) AND MACD Histogram > 0.
3. **Oscillator Filter:** $45 \le \text{RSI}(14) \le 65$ (Confirms active momentum without chasing overbought extremes).
4. **Execution:** Limit order placed near **EMA 20** or recent micro-breakout high.

### 2. Short Entry Conditions (SELL / PUT)
All conditions must be satisfied on a **closed 5m candle**:

1. **Trend Filter:** Price < **EMA 20** < **EMA 50** AND Price < **VWAP**.
2. **Momentum Signal:** MACD Line < Signal Line (or bearish crossover) AND MACD Histogram < 0.
3. **Oscillator Filter:** $35 \le \text{RSI}(14) \le 55$ (Confirms active momentum without chasing oversold extremes).
4. **Execution:** Limit order placed near **EMA 20** or recent micro-breakout low.

---

## 🛡️ Risk & Money Management (5x Leverage Framework)

Leverage is used as a **capital efficiency tool**, not a gambling multiplier. Under a 5x setup, liquidation occurs if price moves against the position by $\approx 18\text{--}20\%$, leaving a wide safety buffer against 5m spikes.

### Position Sizing & Margin Allocation
* **Margin Type:** **Isolated Margin ONLY** (Never use Cross Margin for high-frequency scalping).
* **Account Risk per Trade:** Max **1.0%** of total equity.
* **Margin Allocated per Position:** Max **10% – 20%** of total wallet balance at 5x leverage.
  * *Example:* For a **$10,000** total balance, allocate **$1,500** initial margin. With 5x leverage, position nominal value = **$7,500** (0.75x total account exposure).

### Stop-Loss & Take-Profit Rules
* **Stop-Loss (SL):** **$2 \times \text{ATR}(14)$** or outside the recent 5m swing high/low (typically **0.4% – 0.8%** price distance).
  * *5x Equity Impact:* A 0.6% market drop against position = **3.0% loss on allocated margin** ($0.3\%$ of total equity).
* **Take-Profit (TP):**
  * **TP 1 (50% Position):** $1.5 \times \text{Risk}$ distance (Move SL to Break-Even).
  * **TP 2 (Remaining 50%):** $2.0 \times \text{Risk}$ distance OR exit when MACD bearish crossover occurs / RSI exceeds extreme bounds ($>75$ for Longs, $<25$ for Shorts).

---

## 🐍 Python Backtest Implementation

```python
import pandas as pd
import numpy as np

class BTCScalpingStrategy5x:
    def __init__(self, df: pd.DataFrame, initial_equity: float = 10000.0, leverage: float = 5.0):
        """
        Expects a DataFrame with ['open', 'high', 'low', 'close', 'volume'] indexed by datetime.
        """
        self.df = df.copy()
        self.initial_equity = initial_equity
        self.leverage = leverage

    def calculate_indicators(self) -> pd.DataFrame:
        df = self.df
        
        # Exponential Moving Averages
        df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # Daily/Cumulative VWAP
        tp = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (tp * df['volume']).cumsum() / df['volume'].cumsum()
        
        # MACD (12, 26, 9)
        ema_12 = df['close'].ewm(span=12, adjust=False).mean()
        ema_26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema_12 - ema_26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        
        # RSI (14)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # ATR (14)
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift()).abs(),
            (df['low'] - df['close'].shift()).abs()
        ], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()

        # Signal Logic
        df['signal'] = 0
        long_cond = (
            (df['close'] > df['ema_20']) & 
            (df['ema_20'] > df['ema_50']) & 
            (df['close'] > df['vwap']) & 
            (df['macd'] > df['macd_signal']) & 
            (df['rsi'].between(45, 65))
        )
        short_cond = (
            (df['close'] < df['ema_20']) & 
            (df['ema_20'] < df['ema_50']) & 
            (df['close'] < df['vwap']) & 
            (df['macd'] < df['macd_signal']) & 
            (df['rsi'].between(35, 55))
        )
        
        df.loc[long_cond, 'signal'] = 1
        df.loc[short_cond, 'signal'] = -1
        return df

    def run_backtest(self, taker_fee: float = 0.0004, maker_fee: float = 0.0002, slippage: float = 0.0001):
        df = self.calculate_indicators()
        df['position'] = df['signal'].shift(1).fillna(0)  # Avoid look-ahead bias
        
        # Fee structure assuming 80% Limit (Maker) and 20% Market (Taker) entries
        avg_fee = (0.8 * maker_fee) + (0.2 * taker_fee)
        total_friction = (avg_fee + slippage) * self.leverage
        
        # Returns calculation
        df['raw_ret'] = df['close'].pct_change()
        trades = df['position'].diff().abs().fillna(0)
        df['strat_ret'] = (df['position'] * df['raw_ret'] * self.leverage) - (trades * total_friction)
        df['equity'] = self.initial_equity * (1 + df['strat_ret'].fillna(0)).cumprod()
        
        return df
```

---

## ⚡ Execution Guidelines & Execution Hours

1. **Best Operational Window:** 
   * **12:00 UTC – 20:00 UTC** (London & New York session overlap). High volume ensures tight spreads and reliable indicator readings.
2. **Periods to Avoid:**
   * **FOMC, CPI, NFP release windows** (Extreme volatility causes severe slippage and renders technical indicators invalid).
   * Low-volume Asian weekend sessions ( prone to range sweeps and false breakouts).
3. **Execution Tip:**
   * Use **Post-Only / Limit orders** resting on EMA 20 or VWAP touch to earn Maker rebates rather than paying Taker fees on market orders.