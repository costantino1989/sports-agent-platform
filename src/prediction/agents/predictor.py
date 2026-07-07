"""Agno-based 1X2 prediction agent with a deterministic research branch."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.models.openai.like import OpenAILike
from agno.tools import Toolkit
from agno.tools.website import WebsiteTools
from agno.tools.websearch import WebSearchTools

from src.prediction.agents.rule_scan import DossierRuleScanner
from src.prediction.models import (
    PredictionDraft,
    PredictionResult,
    PredictionUnavailableError,
    RuleSignal,
)
from src.prediction.prompt_compact import compact_dossier_for_model
from src.prediction.prompts import load_prompt
from src.prediction.skills import PlaywrightCliSkill, SafeTerminalSkill
from src.prediction.tools import PredictionToolset
from src.utils import get_logger

if TYPE_CHECKING:
    from agno.run.agent import RunOutput

LOGGER = get_logger()

# A rule signal at or above this priority means the dossier is missing or
# contradicts predictive context, so external research is warranted.
DEEP_RESEARCH_PRIORITY_THRESHOLD = 4

# Research is best-effort: cap tool calls so failed scrapes (e.g. 403s) cannot
# spiral into many retries. If nothing useful is found the prediction still runs
# on the dossier, which already carries the primary evidence.
RESEARCH_TOOL_CALL_LIMIT = 4

# Appended to the deep agent's instructions. The deep branch only runs when
# high-priority signals fired, so here tool use is expected rather than optional.
DEEP_RESEARCH_DIRECTIVE = (
    "High-priority uncertainty signals were detected for this match, so the "
    "dossier alone is not trusted. Before answering you MUST gather external "
    "evidence on a flagged gap: use `web_search` (or `search_news`) to find "
    "relevant links for the specific gap (injuries, expected lineup, team news), "
    "then use `read_url` to read the most relevant result. Do not guess URLs; "
    "always discover them via search first. Only skip research if you can "
    "explicitly justify that no external evidence could change the outcome or "
    "the confidence. Integrate what you find into the rationale and evidence_refs."
)


class MatchPredictionAgent:
    """Predict 1X2 outcomes from dossier markdown with a fast/deep branch.

    A deterministic rule scan decides the path per match. The fast branch calls
    the structured prediction agent directly on the dossier. The deep branch
    (triggered by high-priority signals: missing data, internal inconsistency,
    odds anomaly) is two-phase: a tool-enabled research agent gathers external
    evidence via web search + scraping, then the structured prediction agent
    turns the dossier plus those findings into the final prediction. The split
    is required because on this gateway ``output_schema`` suppresses tool calls.
    """

    def __init__(
        self,
        model_id: str,
        base_url: str,
        api_key: str,
        terminal_timeout_seconds: int = 45,
        model_timeout_seconds: int = 180,
        recent_events: int = 15,
    ) -> None:
        """Initialize models, tools, prompts, and scanner.

        Args:
            model_id: Model identifier on the OpenAI-compatible endpoint.
            base_url: Base URL of the OpenAI-compatible endpoint.
            api_key: API key for the endpoint.
            terminal_timeout_seconds: Timeout for the safe terminal tool.
            model_timeout_seconds: HTTP timeout for model requests.
            recent_events: Play-by-play events kept in the model prompt.
        """

        self._recent_events = max(1, recent_events)
        self._scanner = DossierRuleScanner()
        self._playwright_skill = PlaywrightCliSkill()
        self._terminal_skill = SafeTerminalSkill(
            default_timeout_seconds=terminal_timeout_seconds
        )
        self._tools = PredictionToolset(
            playwright_skill=self._playwright_skill,
            terminal_skill=self._terminal_skill,
        ).build()
        self._system_prompt = load_prompt("prediction_system_prompt.txt")
        self._user_prompt_template = load_prompt("prediction_user_prompt.txt")
        model = OpenAILike(
            id=model_id,
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            timeout=max(5, model_timeout_seconds),
        )
        # Structured, tool-less agent used by both branches to emit the final
        # prediction. On this gateway `output_schema` suppresses tool calls, so
        # research is handled separately by the research agent below.
        self._prediction_agent = Agent(
            model=model,
            instructions=self._system_prompt,
            output_schema=PredictionDraft,
        )
        # Deep-branch phase 1: a tool-enabled agent WITHOUT output_schema (so it
        # reliably calls tools) that gathers external evidence. It adds Agno's
        # web search (returns links) and website scraping (reads a link) toolkits
        # on top of the project tools.
        self._web_tools: list[Toolkit] = [WebSearchTools(), WebsiteTools()]
        research_tools: list[Toolkit | Callable[..., str]] = [
            *self._tools,
            *self._web_tools,
        ]
        self._research_agent = Agent(
            model=model,
            tools=research_tools,
            instructions=f"{self._system_prompt}\n\n{DEEP_RESEARCH_DIRECTIVE}",
            tool_call_limit=RESEARCH_TOOL_CALL_LIMIT,
        )
        LOGGER.info(
            f"Prediction agent configured with Agno model={model_id}, "
            f"research_tools={len(research_tools)} (two-phase deep branch: "
            "research then structure)"
        )

    def predict_from_markdown(self, markdown_path: Path) -> PredictionResult:
        """Generate one 1X2 prediction from a dossier markdown file.

        Args:
            markdown_path: Path to input dossier markdown.

        Returns:
            Structured 1X2 prediction result.
        """

        markdown_text = markdown_path.read_text(encoding="utf-8")
        match_label = self._extract_match_label(markdown_text=markdown_text)
        signals = self._scanner.scan(markdown_text=markdown_text)
        # Scan the full dossier for signals, but send the model a compacted view
        # (recent play-by-play only) to keep the prompt small and fast.
        model_markdown = compact_dossier_for_model(markdown_text, self._recent_events)
        user_prompt = self._build_user_prompt(
            source_file=markdown_path.name,
            match_label=match_label,
            signals=signals,
            dossier_markdown=model_markdown,
        )
        branch = "deep" if self._needs_deep_research(signals) else "fast"
        try:
            if branch == "deep":
                findings = self._research(
                    user_prompt=user_prompt, label=markdown_path.name
                )
                prediction_prompt = self._augment_with_findings(user_prompt, findings)
            else:
                prediction_prompt = user_prompt
            response = self._prediction_agent.run(prediction_prompt)
        except Exception as error:  # noqa: BLE001 - one bad match must not abort the batch
            LOGGER.error(f"Prediction run failed [{markdown_path.name}]: {error}")
            raise PredictionUnavailableError(
                f"Prediction run failed [{markdown_path.name}]: {error}"
            ) from error
        result = self._interpret_response(
            response=response,
            default_match=match_label,
            source_file=markdown_path.name,
        )
        LOGGER.info(
            f"Prediction completed [{markdown_path.name}] via {branch} branch -> "
            f"{result.predicted_result} ({result.success_probability}%)"
        )
        return result

    def _research(self, user_prompt: str, label: str) -> str:
        """Run the tool-enabled research agent and return its text findings.

        A research failure is non-fatal: it degrades to an empty findings string
        so the structured prediction still runs on the dossier alone.
        """

        research_prompt = (
            f"{user_prompt}\n\n"
            "TASK NOW: research only the flagged uncertainty gaps. Use web_search "
            "or search_news to find relevant links, then read_url on the best "
            "results. Report concise factual findings with their source URLs. "
            "Do NOT output the final 1X2 prediction yet."
        )
        try:
            response = self._research_agent.run(research_prompt)
        except Exception as error:  # noqa: BLE001 - research is best-effort
            LOGGER.error(f"Research phase failed [{label}]: {error}")
            return ""
        return str(response.content or "")

    @staticmethod
    def _augment_with_findings(user_prompt: str, findings: str) -> str:
        """Append research findings to the prompt for the structuring phase."""

        if not findings.strip():
            return user_prompt
        return (
            f"{user_prompt}\n\n"
            "External research findings (from web search + scraping):\n"
            f"{findings}\n\n"
            "Now produce the final structured 1X2 prediction, integrating the "
            "dossier and these findings."
        )

    def _interpret_response(
        self,
        response: RunOutput,
        default_match: str,
        source_file: str,
    ) -> PredictionResult:
        """Convert an agent response into a validated prediction result."""

        content = response.content
        if isinstance(content, PredictionDraft):
            return self._build_result_from_draft(
                draft=content,
                default_match=default_match,
                source_file=source_file,
            )
        raise PredictionUnavailableError(
            f"Model returned no structured prediction [{source_file}]. "
            f"Raw output: {str(content)[:500]}"
        )

    @staticmethod
    def _needs_deep_research(signals: list[RuleSignal]) -> bool:
        """Return whether any triggered high-priority signal warrants research."""

        return any(
            signal.triggered and signal.priority >= DEEP_RESEARCH_PRIORITY_THRESHOLD
            for signal in signals
        )

    @staticmethod
    def _build_result_from_draft(
        draft: PredictionDraft,
        default_match: str,
        source_file: str,
    ) -> PredictionResult:
        """Merge a model draft with runtime-only fields into a full result."""

        return PredictionResult(
            match=draft.match.strip() or default_match,
            predicted_result=draft.predicted_result,
            success_probability=draft.success_probability,
            rationale=draft.rationale,
            evidence_refs=draft.evidence_refs,
            over_under_result=draft.over_under_result,
            over_under_line=draft.over_under_line,
            over_under_probability=draft.over_under_probability,
            source_file=source_file,
            outcome="",
        )

    def _build_user_prompt(
        self,
        source_file: str,
        match_label: str,
        signals: list[RuleSignal],
        dossier_markdown: str,
    ) -> str:
        """Build final user prompt from template and runtime context."""

        signals_block = self._render_signals(signals=signals)
        return self._user_prompt_template.format(
            source_file=source_file,
            match_label=match_label,
            signals_block=signals_block,
            dossier_markdown=dossier_markdown,
        )

    @staticmethod
    def _render_signals(signals: list[RuleSignal]) -> str:
        """Render detected signals as compact bullet text."""

        if not signals:
            return "- No explicit high-priority signal detected."
        rendered: list[str] = []
        for signal in signals:
            base = (
                f"- [{signal.priority}] {signal.name}: {signal.details} "
                f"(triggered={signal.triggered})"
            )
            if signal.search_query:
                base += f" | query_hint: {signal.search_query}"
            rendered.append(base)
        return "\n".join(rendered)

    @staticmethod
    def _extract_match_label(markdown_text: str) -> str:
        """Extract match label from section 1 line or fallback placeholder."""

        line_match = re.search(
            r"^- Match:\s*(?P<value>.+)$", markdown_text, re.MULTILINE
        )
        if line_match is None:
            return "Unknown Match"
        return line_match.group("value").strip()
