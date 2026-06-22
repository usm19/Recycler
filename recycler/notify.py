"""Telegram notifications (raw Bot API via requests — no heavy dependency)."""
from __future__ import annotations

import requests

from recycler.config import Settings, load_settings


class Telegram:
    def __init__(self, settings: Settings | None = None):
        s = settings or load_settings()
        self.base = f"https://api.telegram.org/bot{s.telegram_bot_token}"
        self.chat = s.telegram_chat_id
        self.enabled = bool(s.telegram_bot_token and s.telegram_chat_id)

    def send(self, text: str, html: bool = True) -> bool:
        if not self.enabled:
            return False
        data = {"chat_id": self.chat, "text": text, "disable_web_page_preview": True}
        if html:
            data["parse_mode"] = "HTML"
        try:
            r = requests.post(f"{self.base}/sendMessage", data=data, timeout=20)
            ok = r.json().get("ok", False)
            if not ok:
                print("[telegram] not ok:", r.text[:200])
            return ok
        except Exception as e:
            print("[telegram] error:", e)
            return False


def fmt_trade_open(symbol, direction, entry, stop, target, size_lots, risk_dollars) -> str:
    arrow = "🟢 LONG" if direction > 0 else "🔴 SHORT"
    return (f"<b>{arrow} {symbol}</b>\n"
            f"Entry: <code>{entry:.5f}</code>\n"
            f"Stop: <code>{stop:.5f}</code>\n"
            f"Target: <code>{target:.5f}</code>\n"
            f"Size: {size_lots:.2f} lots  (risk ${risk_dollars:,.0f})")


def fmt_trade_close(symbol, reason, pnl, r_multiple, equity) -> str:
    emoji = "✅" if pnl > 0 else ("➖" if pnl == 0 else "❌")
    return (f"{emoji} <b>{symbol} closed</b> ({reason})\n"
            f"P&L: <b>${pnl:,.2f}</b>  ({r_multiple:+.2f}R)\n"
            f"Equity: ${equity:,.2f}")
