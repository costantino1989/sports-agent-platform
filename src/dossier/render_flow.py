"""Render dossier sections related to live match flow and market data."""

from __future__ import annotations

import re
from typing import Any, TypeAlias

from src.dossier.flow_extract import FlowDataExtractor
from src.dossier.render_tools import (
    as_text,
    find_dicts_with_keys,
    format_utc_datetime,
    render_table,
    sanitize_payload,
)
from src.models.dossier import MatchDossierData

JsonDict: TypeAlias = dict[str, Any]

NO_DATA_TEMPLATE = "No data found (source: ESPN API, section: {section}). Suggested action: verify via web search."


class MatchFlowRenderer:
    """Render sections that describe live flow, market, and immediate context."""

    def __init__(self) -> None:
        """Initialize flow renderer dependencies."""

        self._extractor = FlowDataExtractor()

    def render_team_stats(self, data: MatchDossierData) -> str:
        """Render section 4 with full team statistics from available feeds."""

        summary_payload = sanitize_payload(data.summary.data)
        competitors = self._extractor.extract_boxscore_teams(summary_payload=summary_payload)
        if not competitors:
            payload = sanitize_payload(data.core_competition.data)
            if payload is None:
                return f"## 4. Team statistics\n{self._no_data('Team statistics')}"
            competitors = find_dicts_with_keys(payload, {"team", "statistics"}, limit=6)
        headers, rows = self._build_full_stats_table(
            data=data,
            competitors=competitors,
        )
        if not rows:
            return f"## 4. Team statistics\n{self._no_data('Team statistics')}"
        table = render_table(headers=headers, rows=rows)
        intro = (
            "## 4. Team statistics\n"
            "Full statistic comparison from the live boxscore feed."
        )
        return f"{intro}\n\n{table}"

    def render_head_to_head(self, data: MatchDossierData) -> str:
        """Render section 5 with head-to-head table."""

        if not data.head_to_head:
            return f"## 5. Head-to-head\n{self._no_data('Head-to-head')}"
        rows: list[list[str]] = []
        for item in data.head_to_head:
            rows.append(
                [
                    format_utc_datetime(value=item.get("date")),
                    as_text(item.get("name"), "Unknown fixture"),
                    as_text(item.get("phase")),
                    as_text(item.get("status")),
                    as_text(item.get("score")),
                ]
            )
        return (
            "## 5. Head-to-head\n"
            "Recent direct meetings with phase and final result details.\n\n"
            + render_table(["Kickoff (UTC)", "Fixture", "Phase", "Status", "Result"], rows)
        )

    def render_live_stats(self, data: MatchDossierData) -> str:
        """Render section 6 with live events and tactical context."""

        play_rows = self.extract_play_rows(data=data, limit=None)
        if not play_rows:
            return f"## 6. Current live statistics\n{self._no_data('Current live statistics')}"
        status_detail = self.extract_status_detail(data=data)
        return "\n".join(
            [
                "## 6. Current live statistics",
                f"Match flow update: {status_detail}.",
                "Full play-by-play:",
                "",
                render_table(["Minute", "Team", "Event", "Impact"], play_rows),
            ]
        )

    def render_news(self, data: MatchDossierData, section_index: int) -> str:
        """Render section 7 or 13 with full available news content."""

        title = "News and transfer updates" if section_index == 7 else "Latest match and transfer updates"
        rows = self._extractor.extract_news_rows(payload=data.news.data)
        if not rows:
            return f"## {section_index}. {title}\n{self._no_data(title)}"
        return (
            f"## {section_index}. {title}\n"
            "Full ESPN news feed entries for this competition.\n\n"
            + render_table(
                ["Published", "Headline", "Source", "Scope", "Article text", "Link"],
                rows,
            )
        )

    def render_odds(self, data: MatchDossierData) -> str:
        """Render section 8 with market snapshot only."""

        payload = sanitize_payload(data.odds.data)
        if payload is None:
            return f"## 8. Odds\n{self._no_data('Odds')}"
        three_way_rows = self._extractor.extract_three_way_odds_rows(payload=payload)
        spread_total_rows = self._extractor.extract_spread_total_rows(payload=payload)
        blocks = [
            "## 8. Odds",
            "Complete market view using ESPN odds snapshots (Current, Close, Open).",
            "",
        ]
        if three_way_rows:
            blocks.extend(
                [
                    "1X2 odds (decimal):",
                    "",
                    render_table(
                        ["Provider", "Snapshot", "1 (Home)", "X (Draw)", "2 (Away)"],
                        three_way_rows,
                    ),
                    "",
                ]
            )
        else:
            blocks.extend(["No 1X2 lines were returned by ESPN.", ""])
        if spread_total_rows:
            blocks.extend(
                [
                    "Spread and totals (decimal):",
                    "",
                    render_table(
                        [
                            "Provider",
                            "Snapshot",
                            "Home spread",
                            "Away spread",
                            "Total line",
                            "Over",
                            "Under",
                        ],
                        spread_total_rows,
                    ),
                ]
            )
        else:
            blocks.append("No spread/totals lines were returned by ESPN.")
        return "\n".join(blocks)

    def render_match_details(self, data: MatchDossierData) -> str:
        """Render section 9 with meaningful match context."""

        competition = sanitize_payload(data.core_competition.data)
        event = sanitize_payload(data.core_event.data)
        if competition is None and event is None:
            return f"## 9. Single match details\n{self._no_data('Single match details')}"
        neutral_site = self._extractor.extract_first_bool(payload=competition, key="neutralSite")
        venue_context = (
            "Neutral venue (no home-field advantage)."
            if neutral_site is True
            else "Standard home-away venue."
            if neutral_site is False
            else "Venue context unavailable."
        )
        venue = self._extractor.extract_first_text(payload=competition, key="fullName")
        attendance = self._extractor.extract_first_text(payload=competition, key="attendance")
        venue_city, venue_country = self._extract_venue_address(competition=competition)
        competition_group = self._extract_competition_group(competition=competition)
        match_officials = self._extract_match_officials(competition=competition)
        rows = [
            ["Kickoff (UTC)", as_text(data.match.event.date)],
            ["Current status", self.extract_status_detail(data=data)],
            ["Venue", as_text(venue)],
            ["Venue city", venue_city],
            ["Venue country", venue_country],
            ["Competition group", competition_group],
            ["Match officials", match_officials],
            ["Venue context", venue_context],
            ["Attendance", as_text(attendance)],
        ]
        return (
            "## 9. Single match details\n"
            "Contextual details that can influence game dynamics.\n\n"
            + render_table(["Detail", "Value"], rows)
        )

    def extract_play_rows(
        self,
        data: MatchDossierData,
        limit: int | None,
    ) -> list[list[str]]:
        """Extract recent plays into structured rows."""

        return self._extractor.extract_play_rows(data=data, limit=limit)

    def extract_status_detail(self, data: MatchDossierData) -> str:
        """Return current match status detail from event payload."""

        return self._extractor.extract_status_detail(data=data)

    @staticmethod
    def _extract_venue_address(competition: JsonDict | list[Any] | None) -> tuple[str, str]:
        """Extract venue city and country from competition payload.

        Args:
            competition: Core competition payload.

        Returns:
            Venue city and country values.
        """

        venue_candidates = find_dicts_with_keys(
            payload=competition,
            required_keys={"fullName", "address"},
            limit=1,
        )
        if not venue_candidates:
            return as_text(None), as_text(None)
        address = venue_candidates[0].get("address")
        if not isinstance(address, dict):
            return as_text(None), as_text(None)
        return as_text(address.get("city")), as_text(address.get("country"))

    @staticmethod
    def _extract_competition_group(competition: JsonDict | list[Any] | None) -> str:
        """Extract competition group name or abbreviation.

        Args:
            competition: Core competition payload.

        Returns:
            Competition group text.
        """

        if isinstance(competition, dict):
            resolved = competition.get("groupResolved")
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip()
            groups = competition.get("groups")
            if isinstance(groups, dict):
                candidate = groups.get("name") or groups.get("abbreviation")
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
        return as_text(None)

    @staticmethod
    def _extract_match_officials(competition: JsonDict | list[Any] | None) -> str:
        """Extract resolved match officials list from competition payload.

        Args:
            competition: Core competition payload.

        Returns:
            Comma-separated official names.
        """

        if not isinstance(competition, dict):
            return as_text(None)
        officials = competition.get("officialsResolved")
        if not isinstance(officials, list):
            return as_text(None)
        names = [name.strip() for name in officials if isinstance(name, str) and name.strip()]
        if not names:
            return as_text(None)
        return ", ".join(names)

    def _build_full_stats_table(
        self,
        data: MatchDossierData,
        competitors: list[JsonDict],
    ) -> tuple[list[str], list[list[str]]]:
        """Build a complete metric-by-team statistics table.

        Args:
            data: Match dossier aggregate.
            competitors: Competitor dictionaries containing team and stats sections.

        Returns:
            Markdown table headers and rows.
        """

        if not competitors:
            return [], []
        score_by_side = {
            (team.side or "").lower(): as_text(team.score)
            for team in data.match.teams
            if team.side
        }
        team_headers: list[str] = []
        metric_order: list[str] = ["__score__"]
        metric_labels: dict[str, str] = {"__score__": "Score"}
        values_by_metric: dict[str, list[str]] = {}
        team_count = len(competitors)

        for index, competitor in enumerate(competitors):
            team_name = self._extract_team_name(competitor=competitor, index=index)
            side = as_text(competitor.get("homeAway"), "").lower()
            header = f"{team_name} ({side})" if side else team_name
            team_headers.append(header)
            values_by_metric.setdefault("__score__", ["N/A"] * team_count)[index] = as_text(
                competitor.get("score"),
                score_by_side.get(side, "N/A"),
            )
            for stat in self._extract_stat_entries(competitor=competitor):
                key = self._extract_stat_key(stat=stat)
                label = self._extract_stat_label(stat=stat)
                value = self._extract_stat_value(stat=stat)
                if key not in metric_order:
                    metric_order.append(key)
                    metric_labels[key] = label
                values_by_metric.setdefault(key, ["N/A"] * team_count)[index] = value

        headers = ["Metric", *team_headers]
        rows = [[metric_labels[key], *values_by_metric.get(key, ["N/A"] * team_count)] for key in metric_order]
        return headers, rows

    @staticmethod
    def _extract_team_name(competitor: JsonDict, index: int) -> str:
        """Extract team display name from one competitor object."""

        team = competitor.get("team")
        if isinstance(team, dict):
            return as_text(team.get("displayName") or team.get("name"), f"Team {index + 1}")
        return as_text(competitor.get("displayName"), f"Team {index + 1}")

    @staticmethod
    def _extract_stat_entries(competitor: JsonDict) -> list[JsonDict]:
        """Extract list of statistic dictionaries from competitor payload."""

        stats = competitor.get("statistics")
        if not isinstance(stats, list):
            return []
        return [item for item in stats if isinstance(item, dict)]

    @staticmethod
    def _extract_stat_key(stat: JsonDict) -> str:
        """Build a normalized key for one statistic entry."""

        raw_name = stat.get("name") or stat.get("displayName") or stat.get("abbreviation")
        if not isinstance(raw_name, str):
            return "unknown"
        return raw_name.replace(" ", "").replace("_", "").lower()

    @staticmethod
    def _extract_stat_label(stat: JsonDict) -> str:
        """Build display label for one statistic entry."""

        raw_label = stat.get("displayName") or stat.get("name") or stat.get("abbreviation")
        if not isinstance(raw_label, str):
            return "Unknown stat"
        normalized = raw_label.replace("_", " ").strip()
        normalized = re.sub(r"(?<!^)(?=[A-Z])", " ", normalized)
        normalized = " ".join(normalized.split())
        if not normalized:
            return "Unknown stat"
        return f"{normalized[0].upper()}{normalized[1:]}"

    @staticmethod
    def _extract_stat_value(stat: JsonDict) -> str:
        """Extract display value for one statistic entry."""

        value = stat.get("displayValue")
        if value is None:
            value = stat.get("value")
        return as_text(value)

    @staticmethod
    def _no_data(section_name: str) -> str:
        """Build standardized no-data fallback text."""

        return NO_DATA_TEMPLATE.format(section=section_name)
