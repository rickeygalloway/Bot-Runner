"""
core/notifier.py
Notification router.
Reads a bot's notify config and dispatches to Telegram or Gmail SMTP.
Never called directly by bots — the scheduler calls it after each run.

Bot config.yaml shape expected:
  notify:
    provider: telegram   # or "email"
    on: failure          # "success" | "failure" | "always"
"""

from __future__ import annotations

import smtplib
import asyncio
from email.mime.text import MIMEText
from typing import Literal

import core.config as cfg
from core.logger import framework_logger as log

NotifyOn = Literal["success", "failure", "always"]


# ── Public entry point ────────────────────────────────────────────────────────

def notify(
    *,
    bot_name: str,
    status: Literal["success", "failure"],
    message: str,
    notify_config: dict,
) -> None:
    """
    Dispatch a notification if the bot's notify policy matches *status*.

    Parameters
    ----------
    bot_name      : display name from the bot's config.yaml
    status        : outcome of the run — "success" or "failure"
    message       : human-readable result / error text
    notify_config : the ``notify:`` block from the bot's config.yaml
                    e.g. {"provider": "telegram", "on": "failure"}
    """
    if not notify_config:
        return

    on: NotifyOn = notify_config.get("on", "failure")
    provider: str = notify_config.get("provider", "").lower()

    # Decide whether to send
    should_send = (
        on == "always"
        or (on == "success" and status == "success")
        or (on == "failure" and status == "failure")
    )
    if not should_send:
        return

    subject = f"[BotRunner] {bot_name} — {status.upper()}"
    body = f"Bot: {bot_name}\nStatus: {status}\n\n{message}"

    if provider == "telegram":
        _send_telegram(subject=subject, body=body)
    elif provider == "email":
        _send_email(subject=subject, body=body)
    else:
        log.warning("Unknown notify provider '{}' for bot '{}'", provider, bot_name)


# ── Telegram ─────────────────────────────────────────────────────────────────

def _send_telegram(*, subject: str, body: str) -> None:
    """Send a message via python-telegram-bot (synchronous wrapper)."""
    token = cfg.TELEGRAM_BOT_TOKEN
    chat_id = cfg.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        log.warning(
            "Telegram notification skipped — TELEGRAM_BOT_TOKEN or "
            "TELEGRAM_CHAT_ID not set in .env"
        )
        return

    try:
        # python-telegram-bot v20+ is async-first; run in a fresh event loop
        import telegram  # noqa: PLC0415

        text = f"*{subject}*\n\n{body}"

        async def _send() -> None:
            bot = telegram.Bot(token=token)
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
            )

        asyncio.run(_send())
        log.info("Telegram notification sent: {}", subject)
    except Exception as exc:
        log.error("Telegram notification failed: {}", exc)


# ── Email (Gmail SMTP) ────────────────────────────────────────────────────────

def _send_email(*, subject: str, body: str) -> None:
    """Send a plain-text email via Gmail SMTP with STARTTLS."""
    sender   = cfg.EMAIL_SENDER
    password = cfg.EMAIL_PASSWORD
    receiver = cfg.EMAIL_RECEIVER

    if not all([sender, password, receiver]):
        log.warning(
            "Email notification skipped — EMAIL_SENDER, EMAIL_PASSWORD, or "
            "EMAIL_RECEIVER not set in .env"
        )
        return

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = receiver

    try:
        with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(sender, password)
            smtp.sendmail(sender, receiver, msg.as_string())
        log.info("Email notification sent: {}", subject)
    except Exception as exc:
        log.error("Email notification failed: {}", exc)
