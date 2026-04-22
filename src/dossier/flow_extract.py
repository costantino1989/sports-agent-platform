"""Extraction helpers for flow-focused dossier rendering."""

from __future__ import annotations

import re
from typing import Any, TypeAlias

from src.dossier.render_tools import as_text, find_dicts_with_keys, sanitize_payload
from src.models.dossier import MatchDossierData

JsonDict: TypeAlias = dict[str, Any]


class FlowDataExtractor:
    """Extract flow-oriented rows and details from dossier payloads."""

    def extract_play_rows(
        self,
        data: MatchDossierData,
        limit: int | None,
    ) -> list[list[str]]:
        """Extract play-by-play rows with minute/team/event/impact.

        Args:
            data: Match dossier aggregate.
            limit: Maximum rows to return. When None, return all rows.

        Returns:
            Table rows with minute, team, event and impact.
        """

        payload = sanitize_payload(data.plays.data)
        if payload is None:
            return []
        plays = self._extract_plays(payload=payload)
        rows: list[list[str]] = []
        selected_plays = plays if limit is None else plays[-limit:]
        for play in selected_plays:
            clock = play.get("clock")
            minute = as_text(clock.get("displayValue") if isinstance(clock, dict) else clock)
            rows.append(
                [
                    minute,
                    self._extract_play_team_name(play=play),
                    as_text(play.get("text") or play.get("shortText"), "Play update"),
                    self._describe_play_impact(play=play),
                ]
            )
        return rows

    def extract_status_detail(self, data: MatchDossierData) -> str:
        """Return current status detail from event status or summary header."""

        status = data.match.event.status or {}
        if isinstance(status, dict):
            status_type = status.get("type")
            if isinstance(status_type, dict):
                detail = status_type.get("detail")
                if isinstance(detail, str) and detail.strip():
                    return detail.strip()
            direct_detail = status.get("detail") or status.get("name")
            if isinstance(direct_detail, str) and direct_detail.strip():
                return direct_detail.strip()
        return self._extract_summary_status_detail(summary_payload=sanitize_payload(data.summary.data))

    @staticmethod
    def extract_boxscore_teams(summary_payload: JsonDict | list[Any] | None) -> list[JsonDict]:
        """Extract team rows from `summary.boxscore.teams`."""

        if not isinstance(summary_payload, dict):
            return []
        boxscore = summary_payload.get("boxscore")
        if not isinstance(boxscore, dict):
            return []
        teams = boxscore.get("teams")
        if not isinstance(teams, list):
            return []
        return [team for team in teams if isinstance(team, dict)]

    def extract_news_rows(self, payload: JsonDict | list[Any] | None) -> list[list[str]]:
        """Extract full news rows from the ESPN news feed."""

        if payload is None:
            return []
        articles: list[JsonDict] = []
        if isinstance(payload, dict):
            for key in ("articles", "items"):
                raw_items = payload.get(key)
                if isinstance(raw_items, list):
                    articles.extend([item for item in raw_items if isinstance(item, dict)])
        if isinstance(payload, list):
            articles.extend([item for item in payload if isinstance(item, dict)])
        rows: list[list[str]] = []
        for article in articles:
            source = article.get("source")
            source_name = None
            if isinstance(source, dict):
                source_name = source.get("name") or source.get("description")
            links = article.get("links")
            link = None
            if isinstance(links, dict):
                web = links.get("web")
                mobile = links.get("mobile")
                if isinstance(web, dict):
                    link = web.get("href")
                if link is None and isinstance(mobile, dict):
                    link = mobile.get("href")
            article_text = article.get("story") or article.get("description")
            rows.append(
                [
                    as_text(article.get("published") or article.get("lastModified")),
                    as_text(article.get("headline") or article.get("title"), "Untitled"),
                    as_text(source_name or article.get("byline")),
                    as_text(article.get("type"), "League update"),
                    self._normalize_news_text(as_text(article_text)),
                    as_text(link),
                ]
            )
        return rows

    @staticmethod
    def _normalize_news_text(text: str) -> str:
        """Normalize article text to keep markdown tables valid and readable."""

        return " ".join(text.replace("|", "/").split())

    def extract_three_way_odds_rows(self, payload: JsonDict | list[Any]) -> list[list[str]]:
        """Extract complete 1X2 rows across current/close/open snapshots."""

        items = self._collect_odds_items(payload=payload)
        rows: list[list[str]] = []
        for item in items[:8]:
            provider = self._extract_provider_name(item=item)
            for snapshot_key, snapshot_label in self._snapshot_sequence():
                home = self._extract_team_moneyline(
                    item=item,
                    team_key="homeTeamOdds",
                    snapshot_key=snapshot_key,
                )
                draw = self._extract_draw_moneyline(item=item, snapshot_key=snapshot_key)
                away = self._extract_team_moneyline(
                    item=item,
                    team_key="awayTeamOdds",
                    snapshot_key=snapshot_key,
                )
                if all(value == "N/A" for value in (home, draw, away)):
                    continue
                rows.append([provider, snapshot_label, home, draw, away])
        return rows

    def extract_spread_total_rows(self, payload: JsonDict | list[Any]) -> list[list[str]]:
        """Extract complete spread and totals rows across odds snapshots."""

        items = self._collect_odds_items(payload=payload)
        rows: list[list[str]] = []
        for item in items[:8]:
            provider = self._extract_provider_name(item=item)
            for snapshot_key, snapshot_label in self._snapshot_sequence():
                home_spread = self._extract_team_spread(
                    item=item,
                    team_key="homeTeamOdds",
                    snapshot_key=snapshot_key,
                )
                away_spread = self._extract_team_spread(
                    item=item,
                    team_key="awayTeamOdds",
                    snapshot_key=snapshot_key,
                )
                total_line = self._extract_total_line(item=item, snapshot_key=snapshot_key)
                over = self._extract_total_price(
                    item=item,
                    snapshot_key=snapshot_key,
                    market_key="over",
                    fallback_key="overOdds",
                )
                under = self._extract_total_price(
                    item=item,
                    snapshot_key=snapshot_key,
                    market_key="under",
                    fallback_key="underOdds",
                )
                if all(value == "N/A" for value in (home_spread, away_spread, total_line, over, under)):
                    continue
                rows.append(
                    [provider, snapshot_label, home_spread, away_spread, total_line, over, under]
                )
        return rows

    @staticmethod
    def extract_first_bool(payload: JsonDict | list[Any] | None, key: str) -> bool | None:
        """Extract first boolean value for a key from nested payload."""

        if payload is None:
            return None
        matches = find_dicts_with_keys(payload=payload, required_keys={key}, limit=1)
        if not matches:
            return None
        value = matches[0].get(key)
        return value if isinstance(value, bool) else None

    @staticmethod
    def extract_first_text(payload: JsonDict | list[Any] | None, key: str) -> str | None:
        """Extract first text-compatible value for key from nested payload."""

        if payload is None:
            return None
        matches = find_dicts_with_keys(payload=payload, required_keys={key}, limit=1)
        if not matches:
            return None
        return as_text(matches[0].get(key))

    @staticmethod
    def _extract_plays(payload: JsonDict | list[Any]) -> list[JsonDict]:
        """Extract play dictionaries from common payload shapes."""

        plays: list[JsonDict] = []
        if isinstance(payload, dict):
            for key in ("items", "plays"):
                raw_items = payload.get(key)
                if isinstance(raw_items, list):
                    plays.extend([item for item in raw_items if isinstance(item, dict)])
        if not plays:
            plays = find_dicts_with_keys(payload, {"text"}, limit=80)
        return plays

    @staticmethod
    def _extract_summary_status_detail(summary_payload: JsonDict | list[Any] | None) -> str:
        """Extract live status detail from summary header payload."""

        if not isinstance(summary_payload, dict):
            return "Status unavailable"
        header = summary_payload.get("header")
        if not isinstance(header, dict):
            return "Status unavailable"
        competitions = header.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            return "Status unavailable"
        competition = competitions[0]
        if not isinstance(competition, dict):
            return "Status unavailable"
        status = competition.get("status")
        if not isinstance(status, dict):
            return "Status unavailable"
        status_type = status.get("type")
        if isinstance(status_type, dict):
            detail = status_type.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
        return as_text(status.get("displayClock"), "Status unavailable")

    @staticmethod
    def _extract_play_team_name(play: JsonDict) -> str:
        """Extract play team name, with textual fallback from event text."""

        team = play.get("team")
        if isinstance(team, dict):
            display_name = team.get("displayName") or team.get("name")
            if isinstance(display_name, str) and display_name.strip():
                return display_name.strip()
        text = play.get("text") or play.get("shortText") or ""
        if isinstance(text, str):
            match = re.search(r"\(([^()]+)\)", text)
            if match:
                candidate = match.group(1).strip()
                if candidate:
                    return candidate
        return "N/A"

    @staticmethod
    def _collect_odds_items(payload: JsonDict | list[Any]) -> list[JsonDict]:
        """Collect odds item dictionaries from common payload shapes."""

        odds_items: list[JsonDict] = []
        if isinstance(payload, dict):
            for key in ("odds", "items"):
                raw_items = payload.get(key)
                if isinstance(raw_items, list):
                    odds_items.extend([item for item in raw_items if isinstance(item, dict)])
        if isinstance(payload, list):
            odds_items.extend([item for item in payload if isinstance(item, dict)])
        return odds_items

    @staticmethod
    def _snapshot_sequence() -> tuple[tuple[str, str], ...]:
        """Return preferred odds snapshots in display order."""

        return (("current", "Current"), ("close", "Close"), ("open", "Open"))

    @staticmethod
    def _extract_provider_name(item: JsonDict) -> str:
        """Extract provider display name from one odds item."""

        provider = item.get("provider")
        if isinstance(provider, dict):
            return as_text(provider.get("name"))
        return as_text(provider)

    def _extract_team_moneyline(self, item: JsonDict, team_key: str, snapshot_key: str) -> str:
        """Extract one team moneyline for the requested snapshot."""

        team_odds = item.get(team_key)
        if not isinstance(team_odds, dict):
            return "N/A"
        snapshot = team_odds.get(snapshot_key)
        if isinstance(snapshot, dict):
            formatted = self._format_price(snapshot.get("moneyLine"))
            if formatted != "N/A":
                return formatted
        fallback = team_odds.get("moneyLine") if snapshot_key == "current" else None
        return self._format_decimal_from_american(fallback)

    def _extract_draw_moneyline(self, item: JsonDict, snapshot_key: str) -> str:
        """Extract draw moneyline for the requested snapshot."""

        snapshot = item.get(snapshot_key)
        if isinstance(snapshot, dict):
            formatted = self._format_price(snapshot.get("draw"))
            if formatted != "N/A":
                return formatted
        draw_odds = item.get("drawOdds")
        fallback = (
            draw_odds.get("moneyLine")
            if snapshot_key == "current" and isinstance(draw_odds, dict)
            else None
        )
        return self._format_decimal_from_american(fallback)

    def _extract_team_spread(self, item: JsonDict, team_key: str, snapshot_key: str) -> str:
        """Extract spread line and price for one team and snapshot."""

        team_odds = item.get(team_key)
        if not isinstance(team_odds, dict):
            return "N/A"
        line = "N/A"
        price = "N/A"
        snapshot = team_odds.get(snapshot_key)
        if isinstance(snapshot, dict):
            line = self._extract_spread_line(snapshot=snapshot)
            price = self._format_price(snapshot.get("spread"))
        if line == "N/A" and snapshot_key == "current":
            line = self._format_line(
                value=self._fallback_point_spread(item=item, team_key=team_key),
                signed=True,
            )
        if price == "N/A" and snapshot_key == "current":
            price = self._format_decimal_from_american(team_odds.get("spreadOdds"))
        if line == "N/A" and price == "N/A":
            return "N/A"
        if line == "N/A":
            return price
        if price == "N/A":
            return line
        return f"{line} @ {price}"

    def _extract_total_line(self, item: JsonDict, snapshot_key: str) -> str:
        """Extract totals threshold line from the requested snapshot."""

        snapshot = item.get(snapshot_key)
        if isinstance(snapshot, dict):
            total = snapshot.get("total")
            if isinstance(total, dict):
                line = self._format_line(
                    value=total.get("american") or total.get("alternateDisplayValue"),
                    signed=False,
                )
                if line != "N/A":
                    return line
        fallback = item.get("overUnder") if snapshot_key == "current" else None
        return self._format_line(value=fallback, signed=False)

    def _extract_total_price(
        self,
        item: JsonDict,
        snapshot_key: str,
        market_key: str,
        fallback_key: str,
    ) -> str:
        """Extract over/under price from snapshot with top-level fallback."""

        snapshot = item.get(snapshot_key)
        if isinstance(snapshot, dict):
            formatted = self._format_price(snapshot.get(market_key))
            if formatted != "N/A":
                return formatted
        fallback = item.get(fallback_key) if snapshot_key == "current" else None
        return self._format_decimal_from_american(fallback)

    def _extract_spread_line(self, snapshot: JsonDict) -> str:
        """Extract signed spread line from a team snapshot block."""

        point_spread = snapshot.get("pointSpread")
        if isinstance(point_spread, dict):
            return self._format_line(
                value=point_spread.get("american") or point_spread.get("alternateDisplayValue"),
                signed=True,
            )
        return "N/A"

    def _fallback_point_spread(self, item: JsonDict, team_key: str) -> float | None:
        """Build fallback point spread from top-level spread field."""

        raw_spread = item.get("spread")
        spread_value = self._to_float(raw_spread)
        if spread_value is None:
            return None
        return -spread_value if team_key == "awayTeamOdds" else spread_value

    def _format_price(self, value: Any) -> str:
        """Format one odds price in decimal format only."""

        if not isinstance(value, dict):
            return self._format_decimal_from_american(value)
        decimal = self._format_decimal(value.get("decimal") or value.get("value"))
        if decimal != "N/A":
            return decimal
        return self._format_decimal_from_american(
            value.get("american") or value.get("alternateDisplayValue")
        )

    def _format_decimal_from_american(self, value: Any) -> str:
        """Convert American odds into decimal odds format."""

        numeric = self._to_float(value)
        if numeric is None:
            if isinstance(value, str):
                parsed = self._parse_american_string(value=value)
                if parsed is not None:
                    return self._format_decimal(self._american_to_decimal(parsed))
            return "N/A"
        return self._format_decimal(self._american_to_decimal(numeric))

    def _format_decimal(self, value: Any) -> str:
        """Format decimal odds values with compact precision."""

        numeric = self._to_float(value)
        if numeric is None:
            return "N/A"
        return self._format_number(numeric)

    @staticmethod
    def _american_to_decimal(american: float) -> float:
        """Convert one American odds value into decimal odds."""

        if american >= 0:
            return 1.0 + (american / 100.0)
        return 1.0 + (100.0 / abs(american))

    @staticmethod
    def _parse_american_string(value: str) -> float | None:
        """Parse American odds strings like '+125' or '-160'."""

        candidate = value.strip()
        if not candidate:
            return None
        try:
            return float(candidate)
        except ValueError:
            return None

    def _format_line(self, value: Any, signed: bool) -> str:
        """Format spread/total line values with optional sign."""

        numeric = self._to_float(value)
        if numeric is not None:
            text = self._format_number(numeric)
            if signed and numeric > 0 and not text.startswith("+"):
                return f"+{text}"
            return text
        if not isinstance(value, str):
            return "N/A"
        candidate = value.strip()
        if not candidate:
            return "N/A"
        if signed and candidate[0] not in {"+", "-"}:
            parsed = self._to_float(candidate)
            if parsed is not None and parsed > 0:
                return f"+{self._format_number(parsed)}"
        return candidate

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Try converting supported values to float."""

        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None
            try:
                return float(candidate)
            except ValueError:
                return None
        return None

    @staticmethod
    def _format_number(value: float) -> str:
        """Format float values without unnecessary trailing zeroes."""

        return f"{value:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _describe_play_impact(play: JsonDict) -> str:
        """Translate play booleans into a human-readable impact label."""

        if play.get("scoringPlay") is True:
            return "Score changed"
        if play.get("redCard") is True:
            return "Red card shown"
        if play.get("yellowCard") is True:
            return "Yellow card shown"
        if play.get("penaltyKick") is True:
            return "Penalty situation"
        if play.get("ownGoal") is True:
            return "Own-goal situation"
        if play.get("substitution") is True:
            return "Substitution occurred"
        return "General play update"
