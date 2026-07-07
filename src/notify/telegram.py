"""Minimal Telegram Bot API notifier (stdlib only, best-effort).

Sends a message via ``https://api.telegram.org/bot<token>/sendMessage``. Failures
never propagate: a notification is a side channel and must not break the cron
cycle that triggered it.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from collections.abc import Callable

from src.utils import get_logger

LOGGER = get_logger()

_API_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """Send text messages to a fixed Telegram chat via a bot token."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        http_post: Callable[[str, dict], None] | None = None,
    ) -> None:
        """Initialize the notifier.

        Args:
            token: Telegram bot token from @BotFather.
            chat_id: Destination chat id.
            http_post: Injected ``(url, payload)`` sender (for tests); defaults to
                a stdlib urllib POST.
        """

        self._token = token
        self._chat_id = chat_id
        self._http_post = http_post or self._default_post

    def send(self, text: str) -> bool:
        """Send one message; return whether it was dispatched (never raises).

        Args:
            text: Message body (HTML parse mode).

        Returns:
            True when the message was posted, False when disabled or on error.
        """

        if not self._token or not self._chat_id:
            return False
        url = _API_TEMPLATE.format(token=self._token)
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        try:
            self._http_post(url, payload)
        except Exception as error:  # noqa: BLE001 - notification must never break the cycle
            LOGGER.warn(f"Telegram send failed: {error}")
            return False
        return True

    @staticmethod
    def _default_post(url: str, payload: dict) -> None:
        """POST a urlencoded payload to Telegram via urllib."""

        data = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()


def build_telegram_notifier(token: str, chat_id: str) -> TelegramNotifier | None:
    """Build a notifier, or None when Telegram is not configured.

    Args:
        token: Telegram bot token (empty disables notifications).
        chat_id: Destination chat id (empty disables notifications).

    Returns:
        A configured :class:`TelegramNotifier`, or None to disable notifications.
    """

    if not token or not chat_id:
        return None
    return TelegramNotifier(token=token, chat_id=chat_id)
