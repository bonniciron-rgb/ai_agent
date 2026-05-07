"""Vercel serverless entry point for the Telegram webhook.

Vercel maps ``/api/telegram_webhook`` POST requests to this file.
All logic lives in ai_agent.bot.webhook; this file is just the adapter.
"""

from ai_agent.bot.webhook import handle as handler  # noqa: F401
