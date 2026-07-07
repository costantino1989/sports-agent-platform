"""Shared team-name matching helpers for odds providers.

Two independent feeds (ESPN and an odds API) name the same team differently, so
matching is fuzzy: exact, substring, then significant-token overlap. Scores let
callers assign the two team outcomes to home/away bijectively (never swapping 1
and 2) and confirm a same-time event is really the requested match.
"""

from __future__ import annotations

import unicodedata

# Team-name tokens that carry no identifying signal for fuzzy matching.
NOISE_TOKENS = frozenset(
    {"fc", "cf", "sc", "ac", "afc", "club", "national", "team", "cd", "ss", "us"}
)


def normalize(name: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""

    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    kept = "".join(c if c.isalnum() else " " for c in ascii_only.lower())
    return " ".join(kept.split())


def significant_tokens(normalized: str) -> set[str]:
    """Tokens of a normalized name minus generic club/nation noise words."""

    return {tok for tok in normalized.split() if tok not in NOISE_TOKENS}


def match_score(left: str, right: str) -> int:
    """Strength of a name match: exact 3, substring 2, token overlap 1, else 0."""

    left_norm, right_norm = normalize(left), normalize(right)
    if not left_norm or not right_norm:
        return 0
    if left_norm == right_norm:
        return 3
    if left_norm in right_norm or right_norm in left_norm:
        return 2
    left_tokens = significant_tokens(left_norm)
    right_tokens = significant_tokens(right_norm)
    if not left_tokens or not right_tokens:
        return 0
    overlap = left_tokens & right_tokens
    if overlap and len(overlap) / min(len(left_tokens), len(right_tokens)) >= 0.5:
        return 1
    return 0


def teams_match(left: str, right: str) -> bool:
    """Whether two team names refer to the same club (any positive score)."""

    return match_score(left, right) > 0
