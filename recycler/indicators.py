"""Vectorized technical indicators (pandas). Pure functions, no I/O.

Deliberately broad so the chosen strategy — trend-pullback, opening-range
breakout, or mean-reversion — can be implemented without adding more here.
All functions take/return pandas Series aligned to a UTC DatetimeIndex.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's ATR (RMA of true range)."""
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.fillna(100.0).where(avg_loss != 0, 100.0)


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average Directional Index + directional indicators.
    Returns DataFrame with columns: plus_di, minus_di, adx."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(df)
    atr_ = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr_
    minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr_
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx_ = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di, "adx": adx_})


def bollinger(series: pd.Series, period: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = series.rolling(period, min_periods=period).mean()
    std = series.rolling(period, min_periods=period).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    width = (upper - lower) / mid
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower, "width": width})


def donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    upper = df["high"].rolling(period, min_periods=period).max()
    lower = df["low"].rolling(period, min_periods=period).min()
    mid = (upper + lower) / 2.0
    return pd.DataFrame({"upper": upper, "lower": lower, "mid": mid})


def rolling_high(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=1).max()


def rolling_low(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=1).min()


def slope(series: pd.Series, period: int = 5) -> pd.Series:
    """Per-bar slope of a series over `period` bars (linear fit), normalized."""
    return (series - series.shift(period)) / period


def session_vwap(df: pd.DataFrame, session_reset_hour_utc: int = 0) -> pd.Series:
    """Intraday VWAP that resets at a given UTC hour each day.
    Uses typical price * volume. Volume is OANDA tick count (fine for VWAP shape)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = tp * df["volume"].clip(lower=1)
    # group key: date shifted so the session starts at reset hour
    shifted = df.index - pd.Timedelta(hours=session_reset_hour_utc)
    grp = shifted.date
    cum_pv = pv.groupby(grp).cumsum()
    cum_v = df["volume"].clip(lower=1).groupby(grp).cumsum()
    return cum_pv / cum_v
