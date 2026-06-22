"""Red-folder economic-news blackout.

Primary live source: ForexFactory weekly JSON on the FairEconomy CDN (free, no
auth, explicit `impact: "High"` = red folder, `country` field = currency code).
Guard against the silent "Request Denied" HTML body (returned with HTTP 200).

The same NewsCalendar drives the backtest (from a cached CSV of historical
events) and the live bot (from the weekly feed), so the blackout logic is
identical in research and production.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests

from recycler import instruments
from recycler.config import REPO_ROOT

FF_THISWEEK = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_NEXTWEEK = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"
NEWS_DIR = REPO_ROOT / "data" / "news"
NEWS_DIR.mkdir(parents=True, exist_ok=True)

# Tier-1 titles that must be treated as red even if a feed mislabels impact.
TIER1 = ("Non-Farm", "Nonfarm", "NFP", "CPI", "PCE", "FOMC", "Rate Statement",
         "Cash Rate", "Official Bank Rate", "Federal Funds Rate", "Main Refinancing",
         "Monetary Policy", "Employment Change", "Unemployment Rate", "GDP",
         "Interest Rate", "Press Conference")


@dataclass(frozen=True)
class NewsEvent:
    dt_utc: pd.Timestamp
    currency: str
    impact: str
    title: str

    @property
    def is_high(self) -> bool:
        if self.impact.lower().startswith("high") or self.impact.lower() == "red":
            return True
        return any(k.lower() in self.title.lower() for k in TIER1)


def _parse_ff(raw: list[dict]) -> list[NewsEvent]:
    out: list[NewsEvent] = []
    for e in raw:
        try:
            dt = pd.Timestamp(e["date"]).tz_convert("UTC")
        except Exception:
            try:
                dt = pd.Timestamp(e["date"]).tz_localize("UTC")
            except Exception:
                continue
        out.append(NewsEvent(dt, str(e.get("country", "")).upper(),
                             str(e.get("impact", "")), str(e.get("title", ""))))
    return out


def fetch_faireconomy(urls: Iterable[str] = (FF_THISWEEK, FF_NEXTWEEK),
                      cache: bool = True) -> list[NewsEvent]:
    events: list[NewsEvent] = []
    for url in urls:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            body = r.text
            if not body.lstrip().startswith("["):
                raise RuntimeError("FF rate-limited / blocked (non-JSON body)")
            data = json.loads(body)
            events.extend(_parse_ff(data))
        except Exception as exc:  # one feed down must not blind us
            print(f"[news] feed failed {url}: {exc}")
    if cache and events:
        _to_csv(events, NEWS_DIR / "live_cache.csv")
    return events


def _to_csv(events: list[NewsEvent], path: Path) -> None:
    pd.DataFrame([{"dt_utc": e.dt_utc.isoformat(), "currency": e.currency,
                   "impact": e.impact, "title": e.title} for e in events]).to_csv(path, index=False)


def load_csv(path: Path) -> list[NewsEvent]:
    if not Path(path).exists():
        return []
    df = pd.read_csv(path)
    out = []
    for _, r in df.iterrows():
        out.append(NewsEvent(pd.Timestamp(r["dt_utc"]).tz_convert("UTC")
                             if pd.Timestamp(r["dt_utc"]).tzinfo else pd.Timestamp(r["dt_utc"], tz="UTC"),
                             str(r["currency"]).upper(), str(r["impact"]), str(r["title"])))
    return out


class NewsCalendar:
    """Holds high-impact events; answers blackout queries for a pair."""

    def __init__(self, events: list[NewsEvent]):
        self.high = [e for e in events if e.is_high]
        # index by currency for speed
        self._by_ccy: dict[str, list[pd.Timestamp]] = {}
        for e in self.high:
            self._by_ccy.setdefault(e.currency, []).append(e.dt_utc)

    @classmethod
    def live(cls) -> "NewsCalendar":
        return cls(fetch_faireconomy())

    @classmethod
    def from_csv(cls, path) -> "NewsCalendar":
        return cls(load_csv(path))

    def is_blackout(self, t: pd.Timestamp, symbol: str,
                    before_min: int = 30, after_min: int = 120) -> bool:
        """True if a high-impact event for EITHER currency of `symbol` falls in
        [t - before_min, t + after_min]. after_min is generous to cover the hold."""
        ccys = set(instruments.get(symbol).news_ccys)
        lo = t - pd.Timedelta(minutes=before_min)
        hi = t + pd.Timedelta(minutes=after_min)
        for ccy in ccys:
            for dt in self._by_ccy.get(ccy, ()):  # small lists per week
                if lo <= dt <= hi:
                    return True
        return False

    def blackout_fn(self, before_min: int = 30, after_min: int = 120):
        return lambda t, sym: self.is_blackout(t, sym, before_min, after_min)


if __name__ == "__main__":
    cal = NewsCalendar.live()
    print(f"high-impact events loaded: {len(cal.high)}")
    for e in cal.high[:8]:
        print(f"  {e.dt_utc}  {e.currency}  {e.title}")
