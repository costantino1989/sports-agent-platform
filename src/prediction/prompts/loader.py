"""Helpers to load prompt templates from local files."""

from __future__ import annotations

from pathlib import Path


def load_prompt(file_name: str) -> str:
    """Load prompt text from this prompts package directory.

    Args:
        file_name: Prompt file name.

    Returns:
        Prompt text content.
    """

    prompt_path = Path(__file__).resolve().parent / file_name
    return prompt_path.read_text(encoding="utf-8").strip()

