"""Tests for the Telegram notifier and its factory."""

from __future__ import annotations

from src.notify.telegram import TelegramNotifier, build_telegram_notifier


class TestTelegramNotifier:
    def test_send_posts_to_bot_endpoint(self) -> None:
        calls: list[tuple[str, dict]] = []

        def http_post(url: str, payload: dict) -> None:
            calls.append((url, payload))

        notifier = TelegramNotifier("TOKEN", "42", http_post=http_post)
        assert notifier.send("ciao") is True
        url, payload = calls[0]
        assert url == "https://api.telegram.org/botTOKEN/sendMessage"
        assert payload["chat_id"] == "42"
        assert payload["text"] == "ciao"

    def test_send_returns_false_on_error(self) -> None:
        def http_post(url: str, payload: dict) -> None:
            raise OSError("network down")

        notifier = TelegramNotifier("T", "1", http_post=http_post)
        assert notifier.send("x") is False  # best-effort: never raises

    def test_disabled_without_token_or_chat(self) -> None:
        calls: list = []
        notifier = TelegramNotifier("", "1", http_post=lambda u, p: calls.append(1))
        assert notifier.send("x") is False and calls == []


class TestBuildTelegramNotifier:
    def test_none_without_token(self) -> None:
        assert build_telegram_notifier("", "42") is None

    def test_none_without_chat_id(self) -> None:
        assert build_telegram_notifier("TOKEN", "") is None

    def test_builds_when_configured(self) -> None:
        assert isinstance(build_telegram_notifier("TOKEN", "42"), TelegramNotifier)
