"""Value objects for real 1X2 market odds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MatchOdds:
    """Decimal 1X2 odds for one match from a single bookmaker.

    Attributes:
        home: Decimal odds for the home win ("1").
        draw: Decimal odds for the draw ("X").
        away: Decimal odds for the away win ("2").
        bookmaker: Source bookmaker key (e.g. ``betfair_ex_eu``).
        last_update: ISO timestamp of the bookmaker snapshot.
    """

    home: float
    draw: float
    away: float
    bookmaker: str
    last_update: str

    def for_result(self, result: str) -> float | None:
        """Return the decimal odds for a 1X2 result code, or None if unknown."""

        return {"1": self.home, "X": self.draw, "2": self.away}.get(result)
