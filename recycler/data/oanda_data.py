"""OANDA v20 historical candle access with on-disk caching.

Used by BOTH the backtester (bulk history) and the live bot (recent bars), so
the price semantics are identical in research and production.

Key facts baked in (from OANDA v20 docs):
  * instrument names use underscores: EUR_USD, XAU_USD
  * OHLC come back as STRINGS -> float() them
  * `complete=false` is the still-forming bar -> dropped
  * times are RFC3339 nanosecond UTC ("…Z")
  * <=5000 candles/request -> InstrumentsCandlesFactory pages for us
  * no rows are returned across weekend gaps (index by time, not position)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from recycler.config import REPO_ROOT, load_settings

CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_PRICE_KEY = {"M": "mid", "B": "bid", "A": "ask"}

_API = None


def _api():
    global _API
    if _API is None:
        from oandapyV20 import API
        s = load_settings()
        if not s.oanda_api_token:
            raise RuntimeError("OANDA_API_TOKEN missing in .env")
        _API = API(access_token=s.oanda_api_token, environment=s.oanda_environment)
    return _API


def _fmt(dt) -> str:
    """RFC3339 'Z' string OANDA accepts for from/to."""
    if isinstance(dt, str):
        ts = pd.Timestamp(dt)
    else:
        ts = pd.Timestamp(dt)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    # InstrumentsCandlesFactory parses with strict "%Y-%m-%dT%H:%M:%SZ"
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_candles(
    instrument: str,
    granularity: str,
    start=None,
    end=None,
    price: str = "M",
    count: Optional[int] = None,
) -> pd.DataFrame:
    """Fetch candles from OANDA. Returns a UTC-indexed OHLCV DataFrame
    (complete bars only). Either give count (recent) or start/end (range)."""
    api = _api()
    pk = _PRICE_KEY[price]

    rows: list[dict] = []

    def _collect(resp):
        for c in resp.get("candles", []):
            if not c.get("complete", False):
                continue
            px = c.get(pk)
            if not px:
                continue
            rows.append({
                "time": c["time"], "open": float(px["o"]), "high": float(px["h"]),
                "low": float(px["l"]), "close": float(px["c"]),
                "volume": int(c.get("volume", 0) or 0),
            })

    if count and start is None and end is None:
        # count-only: single direct request (factory is range-oriented)
        from oandapyV20.endpoints.instruments import InstrumentsCandles
        req = InstrumentsCandles(instrument=instrument,
                                 params={"granularity": granularity, "price": price,
                                         "count": min(count, 5000)})
        api.request(req)
        _collect(req.response)
    else:
        from oandapyV20.contrib.factories import InstrumentsCandlesFactory
        params: dict = {"granularity": granularity, "price": price}
        if start is not None:
            params["from"] = _fmt(start)
        if end is not None:
            params["to"] = _fmt(end)
        if start is None and end is None:
            params["count"] = count or 500
        for req in InstrumentsCandlesFactory(instrument=instrument, params=params):
            api.request(req)
            _collect(req.response)

    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601")
    df = (df.set_index("time")
            .sort_index())
    df = df[~df.index.duplicated(keep="first")]
    return df


def load_candles(
    instrument: str,
    granularity: str,
    start,
    end,
    price: str = "M",
    refresh: bool = False,
) -> pd.DataFrame:
    """Range fetch with a CSV cache. Re-fetches if cache misses the range."""
    start_ts = pd.Timestamp(start, tz="UTC") if pd.Timestamp(start).tzinfo is None else pd.Timestamp(start).tz_convert("UTC")
    end_ts = pd.Timestamp(end, tz="UTC") if pd.Timestamp(end).tzinfo is None else pd.Timestamp(end).tz_convert("UTC")

    cache = CACHE_DIR / f"{instrument}_{granularity}_{price}.csv"
    if cache.exists() and not refresh:
        df = pd.read_csv(cache)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time").sort_index()
        # Coverage: cached data may legitimately begin a few days after the
        # requested start (market closed / first available bar), so allow slack.
        if (not df.empty and df.index.min() <= start_ts + pd.Timedelta(days=5)
                and df.index.max() >= end_ts - pd.Timedelta(days=4)):
            return df.loc[(df.index >= start_ts) & (df.index <= end_ts)]

    df = get_candles(instrument, granularity, start=start_ts, end=end_ts, price=price)
    if not df.empty:
        out = df.reset_index()
        out.to_csv(cache, index=False)
    return df.loc[(df.index >= start_ts) & (df.index <= end_ts)] if not df.empty else df


def get_last_price(instrument: str) -> Optional[float]:
    """Latest tradeable mid price via the OANDA pricing endpoint."""
    from oandapyV20.endpoints.pricing import PricingInfo
    s = load_settings()
    api = _api()
    r = PricingInfo(accountID=s.oanda_account_id, params={"instruments": instrument})
    api.request(r)
    prices = r.response.get("prices", [])
    if not prices:
        return None
    p = prices[0]
    try:
        bid = float(p["bids"][0]["price"]); ask = float(p["asks"][0]["price"])
        return (bid + ask) / 2.0
    except (KeyError, IndexError, ValueError):
        c = p.get("closeoutBid")
        return float(c) if c else None


def get_recent_frames(symbols, primary_tf, htf, primary_count=320, htf_count=320) -> dict:
    """Recent candles for the live bot (count-based, always fresh, complete bars)."""
    from recycler import instruments
    frames: dict = {}
    for sym in symbols:
        oanda = instruments.get(sym).oanda
        frames[f"{sym}@{primary_tf}"] = get_candles(oanda, primary_tf, count=primary_count)
        frames[f"{sym}@{htf}"] = get_candles(oanda, htf, count=htf_count)
    return frames


def load_frames(symbols, tfs, start, end, price="M", refresh=False) -> dict:
    """Return {'SYM@TF': DataFrame} for canonical symbols (e.g. 'EURUSD') across
    timeframes, mapping to OANDA names internally. Used by backtester + bot."""
    from recycler import instruments
    frames: dict = {}
    for sym in symbols:
        oanda = instruments.get(sym).oanda
        for tf in tfs:
            df = load_candles(oanda, tf, start, end, price=price, refresh=refresh)
            frames[f"{sym}@{tf}"] = df
    return frames


if __name__ == "__main__":
    # quick smoke test
    df = get_candles("EUR_USD", "H1", count=5)
    print(df)
    print("rows:", len(df), "| tz:", df.index.tz)
