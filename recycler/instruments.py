"""Instrument specifications: symbol mapping (OANDA <-> MT5), pip size, digits,
realistic transaction cost, and the currencies whose news affects each pair.

Costs are conservative round-trip estimates (spread + slippage) used by the
backtester so results are not flattered by zero-cost fills. Verify against the
actual FTMO symbol spread at runtime via mt5.symbol_info().
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    symbol: str            # canonical, e.g. "EURUSD"
    oanda: str             # OANDA name, e.g. "EUR_USD"
    mt5_base: str          # MT5 base (suffix resolved at runtime), e.g. "EURUSD"
    pip_size: float        # 0.0001 majors, 0.01 JPY, 0.1 gold
    digits: int
    # round-trip cost in PRICE units (spread + typical slippage), conservative
    cost_price: float
    # value of 1.0 lot per 1.0 price move, in account currency (USD).
    # For USD-quote FX, 1 standard lot = 100,000 units -> $100,000 per 1.0 price.
    contract_per_price: float
    news_ccys: tuple[str, ...]
    is_metal: bool = False


# contract_per_price: USD P&L for a 1.0-price move on 1.0 lot.
# USD-quoted majors (xxxUSD): 100,000 units * 1 = 100,000.
# JPY & xxx-quoted: handled with an approximation in sizing (see backtester).
_SPECS: dict[str, Instrument] = {
    "EURUSD": Instrument("EURUSD", "EUR_USD", "EURUSD", 0.0001, 5, 0.00009, 100_000, ("EUR", "USD")),
    "GBPUSD": Instrument("GBPUSD", "GBP_USD", "GBPUSD", 0.0001, 5, 0.00011, 100_000, ("GBP", "USD")),
    "AUDUSD": Instrument("AUDUSD", "AUD_USD", "AUDUSD", 0.0001, 5, 0.00010, 100_000, ("AUD", "USD")),
    "NZDUSD": Instrument("NZDUSD", "NZD_USD", "NZDUSD", 0.0001, 5, 0.00012, 100_000, ("NZD", "USD")),
    "USDJPY": Instrument("USDJPY", "USD_JPY", "USDJPY", 0.01, 3, 0.012, 100_000, ("USD", "JPY")),
    "USDCAD": Instrument("USDCAD", "USD_CAD", "USDCAD", 0.0001, 5, 0.00012, 100_000, ("USD", "CAD")),
    "EURJPY": Instrument("EURJPY", "EUR_JPY", "EURJPY", 0.01, 3, 0.014, 100_000, ("EUR", "JPY")),
    "GBPJPY": Instrument("GBPJPY", "GBP_JPY", "GBPJPY", 0.01, 3, 0.018, 100_000, ("GBP", "JPY")),
    "XAUUSD": Instrument("XAUUSD", "XAU_USD", "XAUUSD", 0.1, 2, 0.30, 100, ("USD",), is_metal=True),
}


def get(symbol: str) -> Instrument:
    key = symbol.upper().replace("_", "").replace("/", "")
    if key not in _SPECS:
        raise KeyError(f"unknown instrument {symbol!r}; known: {sorted(_SPECS)}")
    return _SPECS[key]


def by_oanda(oanda_symbol: str) -> Instrument:
    for spec in _SPECS.values():
        if spec.oanda == oanda_symbol:
            return spec
    raise KeyError(f"no instrument for OANDA symbol {oanda_symbol!r}")


def all_symbols() -> list[str]:
    return list(_SPECS.keys())


def usd_value_per_price(symbol: str, price: float) -> float:
    """USD P&L for a 1.0 price move on 1.0 lot. Exact for USD-quoted and USD-base
    pairs; crosses approximated via 1/price (excluded from the default universe)."""
    spec = get(symbol)
    base, quote = symbol[:3], symbol[3:6]
    if spec.is_metal or quote == "USD":
        return spec.contract_per_price
    return spec.contract_per_price / price


def lots_for_risk(symbol: str, risk_dollars: float, stop_distance_price: float,
                  ref_price: float) -> float:
    vpp = usd_value_per_price(symbol, ref_price)
    if stop_distance_price <= 0 or vpp <= 0:
        return 0.0
    return risk_dollars / (stop_distance_price * vpp)
