"""Live risk guard — enforces every discipline rule before any order is allowed.

Rules (all hard):
  * One trade per CET day (the user's discipline), within the UTC session window.
  * FTMO daily floor: stop for the day if equity drops `daily_loss_limit` below the
    CET-midnight anchor (buffered under FTMO's real $5,000).
  * FTMO overall floor: halt entirely below initial - `overall_loss_limit` ($9,000
    buffer under FTMO's $10,000 static line).
  * User drawdown guard: stop for the day if equity falls `dd_day_limit` from the
    running peak (defaults to the $1,200 preference).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from recycler.util import cet_day, parse_hm, utc_hm


@dataclass
class RiskConfig:
    account_size: float = 100_000.0
    daily_loss_limit: float = 4_000.0
    overall_loss_limit: float = 9_000.0
    dd_day_limit: float = 1_200.0          # user's max-DD preference (per day, from peak)
    session_start_utc: str = "06:00"
    session_end_utc: str = "16:00"
    max_trades_per_day: int = 1


class RiskGuard:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.day_key = None
        self.day_anchor = cfg.account_size
        self.day_peak = cfg.account_size
        self.peak = cfg.account_size
        self.trades_today = 0
        self.halted_day = False
        self.halted_global = False

    def on_tick(self, now: pd.Timestamp, equity: float) -> None:
        dk = cet_day(now)
        if dk != self.day_key:
            self.day_key = dk
            self.day_anchor = equity
            self.day_peak = equity
            self.trades_today = 0
            self.halted_day = False
        self.peak = max(self.peak, equity)
        self.day_peak = max(self.day_peak, equity)
        # arm halts
        if self.cfg.account_size - equity >= self.cfg.overall_loss_limit:
            self.halted_global = True
        if (self.day_anchor - equity >= self.cfg.daily_loss_limit
                or self.day_peak - equity >= self.cfg.dd_day_limit):
            self.halted_day = True

    def in_session(self, now: pd.Timestamp) -> bool:
        h = utc_hm(now)
        return parse_hm(self.cfg.session_start_utc) <= h <= parse_hm(self.cfg.session_end_utc)

    def can_open(self, now: pd.Timestamp, equity: float) -> tuple[bool, str]:
        self.on_tick(now, equity)
        if self.halted_global:
            return False, "GLOBAL HALT (overall loss limit)"
        if self.halted_day:
            return False, "daily halt (loss/DD limit hit)"
        if self.trades_today >= self.cfg.max_trades_per_day:
            return False, "already traded today"
        if not self.in_session(now):
            return False, "outside session window"
        return True, "ok"

    def register_open(self) -> None:
        self.trades_today += 1
