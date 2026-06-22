"""Strategy contract shared by the backtester and the live bot.

A Strategy looks at completed bars up to index i and may return a Signal that
the execution layer (backtest engine OR live MT5 loop) turns into an order with
a fully specified management plan. The SAME strategy object drives both, so
research and production cannot diverge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class Signal:
    direction: int                       # +1 long, -1 short
    stop: float                          # initial stop price
    # --- management plan (None disables a feature) ---
    target_R: Optional[float] = 2.5      # final take-profit in R multiples
    partial_R: Optional[float] = 1.0     # take a partial at this R
    partial_frac: float = 0.5            # fraction closed at partial_R
    breakeven_after_R: Optional[float] = 1.0  # move SL to entry once this R is reached
    breakeven_buffer_R: float = 0.0      # extra cushion past entry on the BE stop
    trail_atr_mult: Optional[float] = 2.0     # ATR trailing for the runner (None=off)
    max_hold_bars: Optional[int] = None  # force exit after N primary-tf bars
    entry_ref: Optional[float] = None    # informational (decision-bar close)
    tag: str = ""
    meta: dict = field(default_factory=dict)


class Strategy:
    """Base class. Subclasses implement prepare() and generate_signal()."""

    name: str = "base"
    symbols: list[str] = []
    primary_tf: str = "M15"
    htf: Optional[str] = "H4"

    def prepare(self, frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        """Attach indicator columns. `frames` maps a data-key to its OHLCV frame
        (keys like 'EURUSD@M15', 'EURUSD@H4'). Return the (modified) frames."""
        return frames

    def generate_signal(self, symbol: str, frames: dict[str, pd.DataFrame],
                        i: int) -> Optional[Signal]:
        """Decide on the CLOSE of primary-tf bar i (no look-ahead beyond i).
        The engine enters on bar i+1's open. Return None for no trade."""
        raise NotImplementedError

    @staticmethod
    def key(symbol: str, tf: str) -> str:
        return f"{symbol}@{tf}"
