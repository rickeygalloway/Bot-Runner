"""
core/health.py
Environment variable health checks — used by the /setup dashboard route.
"""

from __future__ import annotations

import core.config as cfg


def get_env_status() -> list[dict]:
    """
    Return grouped env var checks with set/unset status and setup instructions.
    Each group maps to a notification provider or bot dependency.
    """
    return [
        {
            "group": "Telegram",
            "description": "Required for Telegram notifications",
            "how_to": (
                "1. Open Telegram and message @BotFather → /newbot → follow prompts → copy the token.\n"
                "2. For your Chat ID, message @userinfobot — it replies with your numeric ID."
            ),
            "vars": [
                {
                    "key": "TELEGRAM_BOT_TOKEN",
                    "label": "Bot Token",
                    "set": bool(cfg.TELEGRAM_BOT_TOKEN),
                },
                {
                    "key": "TELEGRAM_CHAT_ID",
                    "label": "Chat ID",
                    "set": bool(cfg.TELEGRAM_CHAT_ID),
                },
            ],
        },
        {
            "group": "Email (Gmail SMTP)",
            "description": "Required for email notifications",
            "how_to": (
                "1. Enable 2-Step Verification on your Google account.\n"
                "2. Go to Google Account → Security → 2-Step Verification → App passwords.\n"
                "3. Generate a password for 'Mail' and paste it as EMAIL_PASSWORD.\n"
                "   Note: use your full Gmail address for EMAIL_SENDER."
            ),
            "vars": [
                {
                    "key": "EMAIL_SENDER",
                    "label": "Sender address",
                    "set": bool(cfg.EMAIL_SENDER),
                },
                {
                    "key": "EMAIL_PASSWORD",
                    "label": "Gmail App Password",
                    "set": bool(cfg.EMAIL_PASSWORD),
                },
                {
                    "key": "EMAIL_RECEIVER",
                    "label": "Receiver address",
                    "set": bool(cfg.EMAIL_RECEIVER),
                },
            ],
        },
        {
            "group": "OANDA",
            "description": "Required for the Forex Trader bot",
            "how_to": (
                "1. Log in to your OANDA account at oanda.com.\n"
                "2. Go to My Account → Manage API Access → Generate token.\n"
                "3. Your Account ID is shown in the top-right of the dashboard.\n"
                "   Set OANDA_ENV to 'practice' for a demo account or 'live' for real trading."
            ),
            "vars": [
                {
                    "key": "OANDA_API_KEY",
                    "label": "API Key",
                    "set": bool(cfg.OANDA_API_KEY),
                },
                {
                    "key": "OANDA_ACCOUNT_ID",
                    "label": "Account ID",
                    "set": bool(cfg.OANDA_ACCOUNT_ID),
                },
                {
                    "key": "OANDA_ENV",
                    "label": "Environment",
                    "set": bool(cfg.OANDA_ENV),
                },
            ],
        },
    ]


def env_file_exists() -> bool:
    from core.config import ROOT_DIR

    return (ROOT_DIR / ".env").exists()
