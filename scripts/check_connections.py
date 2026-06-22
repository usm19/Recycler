"""One-shot connectivity check for every external integration.

Run:  .venv\\Scripts\\python.exe scripts\\check_connections.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recycler.config import load_settings  # noqa: E402


def mask(s: str, keep: int = 4) -> str:
    if not s:
        return "<empty>"
    return s[:keep] + "…" + s[-keep:] if len(s) > keep * 2 else "***"


def check_oanda(s) -> None:
    print("\n=== OANDA ===")
    try:
        from oandapyV20 import API
        from oandapyV20.endpoints.instruments import InstrumentsCandles
        api = API(access_token=s.oanda_api_token, environment=s.oanda_environment)
        r = InstrumentsCandles(instrument="EUR_USD",
                               params={"granularity": "H1", "count": 5, "price": "M"})
        api.request(r)
        candles = r.response["candles"]
        last = candles[-1]
        print(f"OK  env={s.oanda_environment} got {len(candles)} EUR_USD H1 candles; "
              f"last close={last['mid']['c']} @ {last['time']}")
    except Exception as e:
        print(f"FAIL  {type(e).__name__}: {e}")


def check_supabase(s) -> None:
    print("\n=== SUPABASE ===")
    try:
        import requests
        h = {"apikey": s.supabase_service_key,
             "Authorization": f"Bearer {s.supabase_service_key}"}
        r = requests.get(f"{s.supabase_url}/rest/v1/", headers=h, timeout=15)
        print(f"OK  REST status={r.status_code} (200/400 = key accepted)")
    except Exception as e:
        print(f"FAIL  {type(e).__name__}: {e}")


def check_mt5(s) -> None:
    print("\n=== MT5 / FTMO ===")
    try:
        import MetaTrader5 as mt5
    except Exception as e:
        print(f"FAIL import: {e}")
        return

    kwargs = {}
    if s.mt5_terminal_path:
        kwargs["path"] = s.mt5_terminal_path
    if not mt5.initialize(**kwargs):
        print(f"initialize() failed: {mt5.last_error()}")
        # try bare initialize
        if not mt5.initialize():
            print("bare initialize() also failed — is the terminal installed/closed?")
            return

    # 1) Is the terminal already logged into the target account?
    ai = mt5.account_info()
    if ai and int(ai.login) == int(s.mt5_login):
        ti = mt5.terminal_info()
        print(f"OK  terminal already on account {ai.login} | server={ai.server} | "
              f"balance={ai.balance} equity={ai.equity} currency={ai.currency} "
              f"leverage=1:{ai.leverage} | trade_allowed={getattr(ti,'trade_allowed',None)}")
        print(f"    >>> REAL SERVER NAME = '{ai.server}'  (put this in .env MT5_SERVER)")
        # show a couple of FTMO symbols
        for sym in ("EURUSD", "GBPUSD", "XAUUSD"):
            info = mt5.symbol_info(sym)
            print(f"    symbol {sym}: {'found' if info else 'NOT found — check suffix'}"
                  + (f" spread={info.spread} digits={info.digits}" if info else ""))
        mt5.shutdown()
        return

    # 2) Otherwise try to log in with each candidate password / server
    servers = [s.mt5_server, "FTMO-Demo", "FTMO-Demo2", "FTMO-Server",
               "FTMO-Server2", "FTMO-Server3"]
    seen = set()
    for server in [x for x in servers if x and not (x in seen or seen.add(x))]:
        for label, pw in (("password", s.mt5_password),
                          ("master_password", s.mt5_master_password)):
            if not pw:
                continue
            ok = mt5.login(int(s.mt5_login), password=pw, server=server)
            if ok:
                ai = mt5.account_info()
                ti = mt5.terminal_info()
                print(f"OK  login via {label} on server='{server}' | "
                      f"balance={ai.balance} equity={ai.equity} "
                      f"trade_allowed={getattr(ti,'trade_allowed',None)}")
                print(f"    >>> WORKING: server='{server}', trading password = {label}")
                mt5.shutdown()
                return
    print(f"FAIL  could not log in. last_error={mt5.last_error()}")
    mt5.shutdown()


def main() -> None:
    s = load_settings()
    print("Loaded settings:")
    print(f"  OANDA acct={s.oanda_account_id} token={mask(s.oanda_api_token)}")
    print(f"  MT5 login={s.mt5_login} pw={mask(s.mt5_password)} master={mask(s.mt5_master_password)}")
    print(f"  Supabase url={s.supabase_url}")
    check_oanda(s)
    check_supabase(s)
    check_mt5(s)
    print("\nDone.")


if __name__ == "__main__":
    main()
