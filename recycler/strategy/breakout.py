"""Donchian channel breakout (Turtle-style trend following).

Thesis (documented, decades of evidence): enter on a break of the N-bar
high/low in the trend direction, ride with an ATR trailing stop, cut quick on
failure. Low win rate, high payoff — the classic counterweight to mean-reversion.
Works best as a SWING system (multi-day holds) on H4/D, which on FTMO requires
the Swing account variant (swap-free + no weekend restriction).

Long (mirror short), on close of bar i:
  1. close > Donchian upper(channel) computed on bars before i (no self-reference)
  2. optional trend filter: close > EMA(trend_ema)
  3. ATR volatility band
  4. stop = stop_atr*ATR below entry; ride with trail_atr_mult*ATR trailing stop
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from recycler import indicators as ind
from recycler.strategy.base import Signal, Strategy


class DonchianBreakout(Strategy):
    name = "donchian_breakout"

    def __init__(
        self,
        symbols: list[str],
        primary_tf: str = "H4",
        htf: str = "D",
        channel: int = 20,
        atr_period: int = 14,
        stop_atr: float = 2.0,
        trail_atr_mult: float = 3.0,
        trend_ema: int = 100,
        use_trend: bool = True,
        atr_pct_min: float = 0.0003,
        atr_pct_max: float = 0.03,
        max_hold_bars: Optional[int] = None,
        target_R: Optional[float] = None,
        partial_R: Optional[float] = None,
        partial_frac: float = 0.5,
        breakeven_after_R: Optional[float] = None,
    ):
        self.symbols = symbols
        self.primary_tf = primary_tf
        self.htf = htf
        self.p = dict(channel=channel, atr_period=atr_period, stop_atr=stop_atr,
                      trail_atr_mult=trail_atr_mult, trend_ema=trend_ema,
                      use_trend=use_trend, atr_pct_min=atr_pct_min,
                      atr_pct_max=atr_pct_max, max_hold_bars=max_hold_bars,
                      target_R=target_R, partial_R=partial_R, partial_frac=partial_frac,
                      breakeven_after_R=breakeven_after_R)

    def prepare(self, frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        p = self.p
        for sym in self.symbols:
            df = frames[self.key(sym, self.primary_tf)]
            df["don_hi"] = df["high"].rolling(p["channel"], min_periods=p["channel"]).max().shift(1)
            df["don_lo"] = df["low"].rolling(p["channel"], min_periods=p["channel"]).min().shift(1)
            df["atr"] = ind.atr(df, p["atr_period"])
            df["trend_ema"] = ind.ema(df["close"], p["trend_ema"])
            frames[self.key(sym, self.primary_tf)] = df
        return frames

    def generate_signal(self, symbol, frames, i) -> Optional[Signal]:
        p = self.p
        df = frames[self.key(symbol, self.primary_tf)]
        if i < max(p["channel"], p["trend_ema"]) + 2:
            return None
        c = df["close"].iat[i]
        dhi = df["don_hi"].iat[i]; dlo = df["don_lo"].iat[i]
        atr = df["atr"].iat[i]; tema = df["trend_ema"].iat[i]
        if any(np.isnan(x) for x in (dhi, dlo, atr, tema)) or atr <= 0 or c <= 0:
            return None
        if not (p["atr_pct_min"] <= atr / c <= p["atr_pct_max"]):
            return None

        if c > dhi and (not p["use_trend"] or c > tema):
            return self._sig(+1, c - p["stop_atr"] * atr)
        if c < dlo and (not p["use_trend"] or c < tema):
            return self._sig(-1, c + p["stop_atr"] * atr)
        return None

    def _sig(self, direction, stop) -> Signal:
        p = self.p
        return Signal(direction=direction, stop=stop, target_R=p["target_R"],
                      partial_R=p["partial_R"], partial_frac=p["partial_frac"],
                      breakeven_after_R=p["breakeven_after_R"],
                      trail_atr_mult=p["trail_atr_mult"],
                      max_hold_bars=p["max_hold_bars"], tag=self.name,
                      meta={"score": 1.0})
