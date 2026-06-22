"""Small shared helpers: timeframe math, look-ahead-safe HTF alignment, sessions."""
from __future__ import annotations

import pandas as pd

TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30,
              "H1": 60, "H2": 120, "H4": 240, "D": 1440}


def tf_minutes(tf: str) -> int:
    return TF_MINUTES[tf]


def align_htf(primary_index: pd.DatetimeIndex, htf_df: pd.DataFrame,
              htf_tf: str) -> pd.DataFrame:
    """Reindex higher-timeframe columns onto the primary index using ONLY
    HTF bars that have fully CLOSED by each primary bar's open time.

    OANDA stamps a bar at its OPEN time; it closes at open+duration. We shift
    the HTF index forward by its duration (-> close time) then forward-fill onto
    the primary index, so no unclosed HTF bar can leak into a decision.
    """
    closed = htf_df.copy()
    closed.index = closed.index + pd.Timedelta(minutes=tf_minutes(htf_tf))
    return closed.reindex(primary_index, method="ffill")


def cet_day(ts: pd.Timestamp):
    """FTMO server day key (Central European Time)."""
    return ts.tz_convert("Europe/Berlin").date()


def utc_hm(ts: pd.Timestamp) -> float:
    """Hour-of-day in UTC as a float (e.g. 13:30 -> 13.5)."""
    return ts.hour + ts.minute / 60.0


def parse_hm(s: str) -> float:
    h, m = s.split(":")
    return int(h) + int(m) / 60.0
