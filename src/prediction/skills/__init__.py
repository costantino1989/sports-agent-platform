"""Skill layer for prediction agents."""

from src.prediction.skills.playwright_skill import PlaywrightCliSkill
from src.prediction.skills.terminal_safe import SafeTerminalSkill

__all__ = ["PlaywrightCliSkill", "SafeTerminalSkill"]
