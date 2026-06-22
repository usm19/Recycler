"""Download + cache OANDA history for the backtest window.

Fetches a warmup buffer before the test start so indicators are warm on day 1.
Run:  .venv\\Scripts\\python.exe scripts\\fetch_data.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recycler.data.oanda_data import load_candles  # noqa: E402
from recycler import instruments  # noqa: E402

SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "XAUUSD"]
TFS = ["M15", "H4"]
WARMUP_START = "2025-12-10T00:00:00Z"   # buffer for indicator warmup
END = "2026-06-21T00:00:00Z"


def main():
    for sym in SYMBOLS:
        oanda = instruments.get(sym).oanda
        for tf in TFS:
            t0 = time.time()
            df = load_candles(oanda, tf, WARMUP_START, END, refresh=True)
            print(f"{sym:7s} {tf:3s}: {len(df):6d} bars  "
                  f"[{df.index.min()} -> {df.index.max()}]  ({time.time()-t0:.1f}s)")
    print("done.")


if __name__ == "__main__":
    main()
