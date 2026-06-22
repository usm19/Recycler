"""London Momentum-Continuation Pullback.

Edge: intraday momentum continuation in liquid sessions. In an established
higher-timeframe trend, a shallow pullback to dynamic value (EMA20) that is then
reclaimed with momentum tends to continue. Pure trend-following — no SMC/ICT.

Decision (long; mirror for short), evaluated on the close of M15 bar i:
  1. H4 bias up:      htf_ema20 > htf_ema50 AND htf_adx >= adx_min
  2. Pullback:        price tagged the M15 EMA20 within the last `pullback_lookback`
                      bars, while holding above the M15 EMA50 (shallow dip)
  3. Reclaim/momentum: close > EMA20, bullish bar, RSI rising and in (rsi_lo, rsi_hi)
  4. Volatility OK:   ATR/price within a sane band
  5. Stop:            below the recent swing low (buffer), clamped to [min,max]*ATR

Management is carried on the Signal (scale out 50% @ +1R, breakeven, trail runner).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from recycler import indicators as ind
from recycler.strategy.base import Signal, Strategy
from recycler.util import align_htf


class MomentumPullback(Strategy):
    name = "london_momentum_pullback"

    def __init__(
        self,
        symbols: list[str],
        primary_tf: str = "M15",
        htf: str = "H4",
        ema_fast: int = 20,
        ema_slow: int = 50,
        rsi_period: int = 14,
        atr_period: int = 14,
        adx_min: float = 20.0,
        rsi_lo: float = 40.0,
        rsi_hi: float = 68.0,
        pullback_lookback: int = 4,
        swing_lookback: int = 6,
        min_stop_atr: float = 0.8,
        max_stop_atr: float = 2.5,
        stop_buffer_atr: float = 0.1,
        atr_pct_min: float = 0.0004,   # ATR/price floor (skip dead markets)
        atr_pct_max: float = 0.010,    # ATR/price ceiling (skip blow-offs)
        target_R: float = 2.5,
        partial_R: float = 1.0,
        partial_frac: float = 0.5,
        breakeven_after_R: float = 1.0,
        trail_atr_mult: float = 2.0,
        max_hold_bars: int = 16,
        macro_filter: bool = False,
        macro_fast: int = 50,
        macro_slow: int = 200,
    ):
        self.symbols = symbols
        self.primary_tf = primary_tf
        self.htf = htf
        self.p = dict(
            ema_fast=ema_fast, ema_slow=ema_slow, rsi_period=rsi_period,
            atr_period=atr_period, adx_min=adx_min, rsi_lo=rsi_lo, rsi_hi=rsi_hi,
            pullback_lookback=pullback_lookback, swing_lookback=swing_lookback,
            min_stop_atr=min_stop_atr, max_stop_atr=max_stop_atr,
            stop_buffer_atr=stop_buffer_atr, atr_pct_min=atr_pct_min,
            atr_pct_max=atr_pct_max, target_R=target_R, partial_R=partial_R,
            partial_frac=partial_frac, breakeven_after_R=breakeven_after_R,
            trail_atr_mult=trail_atr_mult, max_hold_bars=max_hold_bars,
            macro_filter=macro_filter, macro_fast=macro_fast, macro_slow=macro_slow,
        )

    def prepare(self, frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        p = self.p
        for sym in self.symbols:
            df = frames[self.key(sym, self.primary_tf)]
            df["ema_fast"] = ind.ema(df["close"], p["ema_fast"])
            df["ema_slow"] = ind.ema(df["close"], p["ema_slow"])
            df["rsi"] = ind.rsi(df["close"], p["rsi_period"])
            df["atr"] = ind.atr(df, p["atr_period"])
            touched = (df["low"] <= df["ema_fast"]) & (df["high"] >= df["ema_fast"])
            touched |= (df["low"] <= df["ema_fast"])  # any tag of/through value
            df["pullback_recent"] = touched.rolling(p["pullback_lookback"], min_periods=1).max().astype(bool)
            # symmetric short-side pullback: price tagged EMA from below
            touched_dn = (df["high"] >= df["ema_fast"])
            df["pullback_recent_dn"] = touched_dn.rolling(p["pullback_lookback"], min_periods=1).max().astype(bool)
            df["swing_low"] = df["low"].rolling(p["swing_lookback"], min_periods=1).min()
            df["swing_high"] = df["high"].rolling(p["swing_lookback"], min_periods=1).max()

            # HTF trend, look-ahead safe
            hdf = frames[self.key(sym, self.htf)]
            htf_ind = pd.DataFrame(index=hdf.index)
            htf_ind["htf_ema_fast"] = ind.ema(hdf["close"], p["ema_fast"])
            htf_ind["htf_ema_slow"] = ind.ema(hdf["close"], p["ema_slow"])
            htf_ind["htf_adx"] = ind.adx(hdf, p["atr_period"])["adx"]
            htf_ind["htf_macro_fast"] = ind.ema(hdf["close"], p["macro_fast"])
            htf_ind["htf_macro_slow"] = ind.ema(hdf["close"], p["macro_slow"])
            aligned = align_htf(df.index, htf_ind, self.htf)
            for col in ("htf_ema_fast", "htf_ema_slow", "htf_adx",
                        "htf_macro_fast", "htf_macro_slow"):
                df[col] = aligned[col].to_numpy()
            frames[self.key(sym, self.primary_tf)] = df
        return frames

    def generate_signal(self, symbol: str, frames: dict[str, pd.DataFrame],
                        i: int) -> Optional[Signal]:
        p = self.p
        df = frames[self.key(symbol, self.primary_tf)]
        if i < max(p["ema_slow"], p["swing_lookback"]) + 2:
            return None

        c = df["close"].iat[i]
        o = df["open"].iat[i]
        ema_f = df["ema_fast"].iat[i]
        ema_s = df["ema_slow"].iat[i]
        rsi = df["rsi"].iat[i]
        rsi_prev = df["rsi"].iat[i - 1]
        atr = df["atr"].iat[i]
        hf = df["htf_ema_fast"].iat[i]
        hs = df["htf_ema_slow"].iat[i]
        hadx = df["htf_adx"].iat[i]
        mf = df["htf_macro_fast"].iat[i] if "htf_macro_fast" in df.columns else hf
        ms = df["htf_macro_slow"].iat[i] if "htf_macro_slow" in df.columns else hs

        if any(np.isnan(x) for x in (ema_f, ema_s, rsi, rsi_prev, atr, hf, hs, hadx)):
            return None
        macro_up = (mf > ms) if not np.isnan(mf) and not np.isnan(ms) else True
        if atr <= 0 or c <= 0:
            return None
        atr_pct = atr / c
        if not (p["atr_pct_min"] <= atr_pct <= p["atr_pct_max"]):
            return None
        if hadx < p["adx_min"]:
            return None

        # ---------- LONG ----------
        if hf > hs and (macro_up or not p["macro_filter"]):  # HTF uptrend (+ macro)
            pulled = bool(df["pullback_recent"].iat[i])
            reclaim = c > ema_f and c > o and c > df["close"].iat[i - 1]
            held = c > ema_s  # pullback stayed above slow EMA
            rsi_ok = (rsi > rsi_prev) and (p["rsi_lo"] <= rsi <= p["rsi_hi"])
            if pulled and reclaim and held and rsi_ok:
                swing = df["swing_low"].iat[i]
                stop = swing - p["stop_buffer_atr"] * atr
                dist = c - stop
                if dist < p["min_stop_atr"] * atr:
                    stop = c - p["min_stop_atr"] * atr
                    dist = c - stop
                if dist > p["max_stop_atr"] * atr:
                    return None
                return self._signal(+1, stop, hadx)

        # ---------- SHORT ----------
        if hf < hs and ((not macro_up) or not p["macro_filter"]):  # HTF downtrend (+ macro)
            pulled = bool(df["pullback_recent_dn"].iat[i])
            reclaim = c < ema_f and c < o and c < df["close"].iat[i - 1]
            held = c < ema_s
            rsi_ok = (rsi < rsi_prev) and ((100 - p["rsi_hi"]) <= rsi <= (100 - p["rsi_lo"]))
            if pulled and reclaim and held and rsi_ok:
                swing = df["swing_high"].iat[i]
                stop = swing + p["stop_buffer_atr"] * atr
                dist = stop - c
                if dist < p["min_stop_atr"] * atr:
                    stop = c + p["min_stop_atr"] * atr
                    dist = stop - c
                if dist > p["max_stop_atr"] * atr:
                    return None
                return self._signal(-1, stop, hadx)

        return None

    def _signal(self, direction: int, stop: float, score: float) -> Signal:
        p = self.p
        return Signal(
            direction=direction, stop=stop,
            target_R=p["target_R"], partial_R=p["partial_R"], partial_frac=p["partial_frac"],
            breakeven_after_R=p["breakeven_after_R"], trail_atr_mult=p["trail_atr_mult"],
            max_hold_bars=p["max_hold_bars"], tag=self.name,
            meta={"score": float(score)},
        )
