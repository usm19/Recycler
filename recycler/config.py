"""Central configuration. Loads secrets from the gitignored .env at repo root.

Single chokepoint for all credentials and tunable knobs so the backtester and
the live bot share exactly one source of truth.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        # dotenv optional; fall back to the ambient environment
        pass


def _f(v: str | None, default: float) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _i(v: str | None, default: int) -> int:
    try:
        return int(float(v)) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # OANDA (data + research + paper)
    oanda_api_token: str
    oanda_account_id: str
    oanda_env: str  # "practice" | "live"

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # MT5 / FTMO
    mt5_login: int
    mt5_password: str         # candidate trading/investor password
    mt5_master_password: str  # candidate master (trading) password
    mt5_server: str
    mt5_terminal_path: str

    # Bot
    account_size: float
    max_drawdown_dollars: float
    run_mode: str  # "paper" | "live"

    @property
    def oanda_environment(self) -> str:
        env = (self.oanda_env or "practice").strip().lower()
        return "live" if env in ("live", "trade", "production") else "practice"


def load_settings() -> Settings:
    _load_env()
    g = os.environ.get
    return Settings(
        oanda_api_token=g("OANDA_API_TOKEN", "") or "",
        oanda_account_id=g("OANDA_ACCOUNT_ID", "") or "",
        oanda_env=g("OANDA_ENV", "practice") or "practice",
        telegram_bot_token=g("TELEGRAM_BOT_TOKEN", "") or "",
        telegram_chat_id=g("TELEGRAM_CHAT_ID", "") or "",
        supabase_url=g("SUPABASE_URL", "") or "",
        supabase_service_key=g("SUPABASE_SERVICE_KEY", "") or "",
        mt5_login=_i(g("MT5_LOGIN"), 0),
        mt5_password=g("MT5_PASSWORD", "") or "",
        mt5_master_password=g("MT5_MASTER_PASSWORD", "") or "",
        mt5_server=g("MT5_SERVER", "FTMO-Demo") or "FTMO-Demo",
        mt5_terminal_path=g("MT5_TERMINAL_PATH", "") or "",
        account_size=_f(g("ACCOUNT_SIZE"), 100000.0),
        max_drawdown_dollars=_f(g("MAX_DRAWDOWN_DOLLARS"), 1200.0),
        run_mode=(g("RUN_MODE", "paper") or "paper").strip().lower(),
    )
