"""Rule-based dossier scan to detect targeted research needs."""

from __future__ import annotations

import re
from collections import defaultdict

from src.models.no_data import NO_DATA_SECTION_PATTERN
from src.prediction.models import RuleSignal

ODDS_ROW_PATTERN = re.compile(
    r"^\|\s*(?P<provider>[^|]+)\|\s*(?P<snapshot>[^|]+)\|\s*(?P<home>[^|]+)\|\s*(?P<draw>[^|]+)\|\s*(?P<away>[^|]+)\|$"
)
SCORER_PATTERN = re.compile(r"Goal!.*?\.\s+(?P<player>[A-Za-zÀ-ÖØ-öø-ÿ'`\-.\s]+?)\s+\(")


class DossierRuleScanner:
    """Extract rule triggers from markdown dossier text."""

    def scan(self, markdown_text: str) -> list[RuleSignal]:
        """Scan dossier and return ordered rule signals."""

        signals: list[RuleSignal] = []
        signals.extend(self._scan_no_data(markdown_text=markdown_text))
        signals.extend(self._scan_internal_inconsistency(markdown_text=markdown_text))
        odds_signal = self._scan_odds_delta(markdown_text=markdown_text)
        if odds_signal is not None:
            signals.append(odds_signal)
        late_signal = self._scan_late_momentum(markdown_text=markdown_text)
        if late_signal is not None:
            signals.append(late_signal)
        discipline_signal = self._scan_discipline_risk(markdown_text=markdown_text)
        if discipline_signal is not None:
            signals.append(discipline_signal)
        return sorted(
            signals,
            key=lambda signal: (not signal.triggered, -signal.priority, signal.name),
        )

    def _scan_no_data(self, markdown_text: str) -> list[RuleSignal]:
        """Create one signal for each explicit no-data section."""

        signals: list[RuleSignal] = []
        for match in NO_DATA_SECTION_PATTERN.finditer(markdown_text):
            section_name = match.group("section").strip()
            query = self._query_for_section(section_name=section_name)
            signals.append(
                RuleSignal(
                    name="explicit_no_data",
                    triggered=True,
                    details=(
                        f"Section '{section_name}' is empty in dossier and may hide "
                        "predictive context."
                    ),
                    search_query=query,
                    priority=4,
                )
            )
        return signals

    def _scan_internal_inconsistency(self, markdown_text: str) -> list[RuleSignal]:
        """Detect scorer names that are absent from listed on-field players."""

        listed_players = self._extract_listed_players(markdown_text=markdown_text)
        if not listed_players:
            return []
        unmatched_scorers: list[str] = []
        for scorer_match in SCORER_PATTERN.finditer(markdown_text):
            scorer = scorer_match.group("player").strip()
            if scorer and scorer not in listed_players:
                unmatched_scorers.append(scorer)
        if not unmatched_scorers:
            return []
        scorer_text = ", ".join(sorted(set(unmatched_scorers)))
        return [
            RuleSignal(
                name="internal_inconsistency",
                triggered=True,
                details=(
                    "Potential inconsistency detected: scorer(s) not found among "
                    f"listed players ({scorer_text})."
                ),
                search_query=f"{scorer_text} lineup match report",
                priority=5,
            )
        ]

    def _scan_odds_delta(self, markdown_text: str) -> RuleSignal | None:
        """Detect significant open-vs-live odds deltas."""

        rows = self._extract_odds_rows(markdown_text=markdown_text)
        if not rows:
            return None
        grouped_rows: dict[str, dict[str, tuple[float, float, float]]] = defaultdict(dict)
        for provider, snapshot, home, draw, away in rows:
            grouped_rows[provider][snapshot.lower()] = (home, draw, away)
        max_delta = 0.0
        max_provider = ""
        for provider, snapshots in grouped_rows.items():
            if "open" not in snapshots or "current" not in snapshots:
                continue
            open_home, open_draw, open_away = snapshots["open"]
            cur_home, cur_draw, cur_away = snapshots["current"]
            deltas = [
                self._relative_delta(open_home, cur_home),
                self._relative_delta(open_draw, cur_draw),
                self._relative_delta(open_away, cur_away),
            ]
            provider_delta = max(deltas)
            if provider_delta > max_delta:
                max_delta = provider_delta
                max_provider = provider
        if max_delta < 0.2:
            return None
        percentage = round(max_delta * 100, 1)
        return RuleSignal(
            name="odds_delta_anomaly",
            triggered=True,
            details=(
                f"Significant market movement detected (max delta {percentage}% at {max_provider})."
            ),
            search_query="live soccer odds movement reason team news injuries red card",
            priority=5,
        )

    def _scan_late_momentum(self, markdown_text: str) -> RuleSignal | None:
        """Trigger temporal deepening signal after minute 60."""

        clock_match = re.search(r"- Match clock/detail:\s*(?P<clock>.+)", markdown_text)
        if clock_match is None:
            return None
        minute_value = self._extract_minute(clock_text=clock_match.group("clock"))
        if minute_value < 60:
            return None
        return RuleSignal(
            name="late_game_momentum",
            triggered=True,
            details=(
                f"Match is in minute {minute_value}. Verify last 15-minute momentum "
                "because cumulative stats may hide trend changes."
            ),
            search_query="last 15 minutes match momentum substitutions cards pressure",
            priority=3,
        )

    @staticmethod
    def _scan_discipline_risk(markdown_text: str) -> RuleSignal | None:
        """Detect elevated discipline risk from season YC/RC values."""

        heavy_cards = re.findall(
            r"YC:\s*(?P<yc>\d+);\s*RC:\s*(?P<rc>\d+)",
            markdown_text,
        )
        high_risk_count = 0
        for yellow_cards, red_cards in heavy_cards:
            if int(red_cards) >= 2 or int(yellow_cards) >= 8:
                high_risk_count += 1
        if high_risk_count == 0:
            return None
        return RuleSignal(
            name="discipline_risk",
            triggered=True,
            details=(
                "Multiple players with elevated season YC/RC burden are present. "
                "Assess red-card risk under live match tension."
            ),
            search_query="player disciplinary record latest suspensions risk red card",
            priority=3,
        )

    @staticmethod
    def _extract_listed_players(markdown_text: str) -> set[str]:
        """Extract listed player names from section 2 tables."""

        players: set[str] = set()
        for line in markdown_text.splitlines():
            if not line.startswith("| "):
                continue
            if " | " not in line:
                continue
            chunks = [chunk.strip() for chunk in line.strip("|").split("|")]
            if len(chunks) < 2 or chunks[0] in {"Player", "---"}:
                continue
            player_name = chunks[0]
            if player_name:
                players.add(player_name)
        return players

    def _extract_odds_rows(self, markdown_text: str) -> list[tuple[str, str, float, float, float]]:
        """Extract parsed odds rows from section 8 markdown table."""

        rows: list[tuple[str, str, float, float, float]] = []
        for raw_line in markdown_text.splitlines():
            match = ODDS_ROW_PATTERN.match(raw_line)
            if match is None:
                continue
            provider = match.group("provider").strip()
            snapshot = match.group("snapshot").strip()
            home_value = self._to_decimal(match.group("home"))
            draw_value = self._to_decimal(match.group("draw"))
            away_value = self._to_decimal(match.group("away"))
            if min(home_value, draw_value, away_value) <= 1.0:
                continue
            rows.append((provider, snapshot, home_value, draw_value, away_value))
        return rows

    @staticmethod
    def _to_decimal(value: str) -> float:
        """Convert table cell text to decimal float."""

        cleaned = value.strip().replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    @staticmethod
    def _relative_delta(old_value: float, new_value: float) -> float:
        """Compute absolute relative delta between two positive values."""

        if old_value <= 0:
            return 0.0
        return abs(new_value - old_value) / old_value

    @staticmethod
    def _extract_minute(clock_text: str) -> int:
        """Extract minute integer from ESPN match clock text."""

        match = re.search(r"(?P<minute>\d+)", clock_text)
        if match is None:
            return 0
        return int(match.group("minute"))

    @staticmethod
    def _query_for_section(section_name: str) -> str:
        """Generate focused search query suggestion by missing section name."""

        lowered = section_name.lower()
        if "injur" in lowered:
            return "team injuries unavailable expected lineup absences"
        if "leaders" in lowered or "top scorer" in lowered:
            return "team top scorers current season form"
        if "news" in lowered:
            return "latest team news manager press conference"
        return f"{section_name} latest updates"
