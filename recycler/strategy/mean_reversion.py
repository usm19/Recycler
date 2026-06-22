"""RSI(2) mean-reversion in a higher-timeframe trend (Connors-style).

Thesis (documented, large-sample edge in equities and many FX pairs): in an
established uptrend, a SHORT-TERM oversold extreme (RSI2 very low) tends to snap
back to the mean. We buy the extreme itself (not a bounce confirmation), target
the mean, and cap risk with a hard stop. High win rate by construction; the
honest cost is occasional larger losses (bounded by the stop), which is why the
$1,200 cap drives sizing.

Long (mirror for short), on close of bar i:
  1. Trend up:   close > EMA(trend_ema)   [+ optional H4 trend agreement]
  2. Oversold:   RSI(rsi_period) < rsi_buy
  3. Not in a vol blow-off (ATR/price band)
  4. Stop:       max(stop_atr*ATR, below recent swing) — give reversion room
  5. Target:     small R (revert to mean); managed by the engine's target_R
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from recycler import indicators as ind
from recycler.strategy.base import Signal, Strategy
from recycler.util import align_htf


class MeanReversionRSI2(Strategy):
    name = "mr_rsi2"

    def __init__(
        self,
        symbols: list[str],
        primary_tf: str = "M15",
        htf: str = "H4",
        trend_ema: int = 200,
        rsi_period: int = 2,
        rsi_buy: float = 5.0,
        rsi_sell: float = 95.0,
        atr_period: int = 14,
        stop_atr: float = 2.5,
        swing_lookback: int = 10,
        stop_buffer_atr: float = 0.1,
        target_R: float = 1.0,
        max_hold_bars: int = 12,
        atr_pct_min: float = 0.0003,
        atr_pct_max: float = 0.012,
        use_htf_trend: bool = True,
        require_down_day: bool = True,   # entry bar closes against trend (true dip)
    ):
        self.symbols = symbols
        self.primary_tf = primary_tf
        self.htf = htf
        self.p = dict(
            trend_ema=trend_ema, rsi_period=rsi_period, rsi_buy=rsi_buy, rsi_sell=rsi_sell,
            atr_period=atr_period, stop_atr=stop_atr, swing_lookback=swing_lookback,
            stop_buffer_atr=stop_buffer_atr, target_R=target_R, max_hold_bars=max_hold_bars,
            atr_pct_min=atr_pct_min, atr_pct_max=atr_pct_max, use_htf_trend=use_htf_trend,
            require_down_day=require_down_day,
        )

    def prepare(self, frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        p = self.p
        for sym in self.symbols:
            df = frames[self.key(sym, self.primary_tf)]
            df["trend_ema"] = ind.ema(df["close"], p["trend_ema"])
            df["rsi2"] = ind.rsi(df["close"], p["rsi_period"])
            df["atr"] = ind.atr(df, p["atr_period"])
            df["swing_low"] = df["low"].rolling(p["swing_lookback"], min_periods=1).min()
            df["swing_high"] = df["high"].rolling(p["swing_lookback"], min_periods=1).max()
            if p["use_htf_trend"]:
                hdf = frames[self.key(sym, self.htf)]
                hi = pd.DataFrame(index=hdf.index)
                hi["htf_ema_fast"] = ind.ema(hdf["close"], 20)
                hi["htf_ema_slow"] = ind.ema(hdf["close"], 50)
                aligned = align_htf(df.index, hi, self.htf)
                df["htf_up"] = (aligned["htf_ema_fast"] > aligned["htf_ema_slow"]).to_numpy()
            else:
                df["htf_up"] = True
            frames[self.key(sym, self.primary_tf)] = df
        return frames

    def generate_signal(self, symbol, frames, i) -> Optional[Signal]:
        p = self.p
        df = frames[self.key(symbol, self.primary_tf)]
        if i < p["trend_ema"] + 2:
            return None
        c = df["close"].iat[i]; o = df["open"].iat[i]
        tema = df["trend_ema"].iat[i]; rsi = df["rsi2"].iat[i]; atr = df["atr"].iat[i]
        if any(np.isnan(x) for x in (tema, rsi, atr)) or atr <= 0 or c <= 0:
            return None
        if not (p["atr_pct_min"] <= atr / c <= p["atr_pct_max"]):
            return None
        htf_up = bool(df["htf_up"].iat[i]) if "htf_up" in df else True

        # LONG: uptrend + oversold extreme
        if c > tema and (htf_up or not p["use_htf_trend"]) and rsi < p["rsi_buy"]:
            if p["require_down_day"] and not (c < o):
                return None
            swing = df["swing_low"].iat[i]
            stop = min(swing - p["stop_buffer_atr"] * atr, c - p["stop_atr"] * atr)
            if c - stop <= 0:
                return None
            return self._sig(+1, stop)

        # SHORT: downtrend + overbought extreme
        if c < tema and ((not htf_up) or not p["use_htf_trend"]) and rsi > p["rsi_sell"]:
            if p["require_down_day"] and not (c > o):
                return None
            swing = df["swing_high"].iat[i]
            stop = max(swing + p["stop_buffer_atr"] * atr, c + p["stop_atr"] * atr)
            if stop - c <= 0:
                return None
            return self._sig(-1, stop)

        return None

    def _sig(self, direction, stop) -> Signal:
        p = self.p
        return Signal(direction=direction, stop=stop, target_R=p["target_R"],
                      partial_R=None, breakeven_after_R=None, trail_atr_mult=None,
                      max_hold_bars=p["max_hold_bars"], tag=self.name,
                      meta={"score": 1.0})
