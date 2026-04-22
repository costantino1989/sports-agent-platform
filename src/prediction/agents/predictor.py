"""LangGraph-based 1X2 prediction agent."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from pydantic import ValidationError

from src.prediction.agents.rule_scan import DossierRuleScanner
from src.prediction.models import PredictionResult, RuleSignal
from src.prediction.prompts import load_prompt
from src.prediction.skills import PlaywrightCliSkill, SafeTerminalSkill
from src.prediction.tools import PredictionToolset
from src.utils import get_logger

LOGGER = get_logger()
JSON_BLOCK_PATTERN = re.compile(r"\{[\s\S]*\}")


class MatchPredictionAgent:
    """Predict 1X2 outcomes from dossier markdown with targeted tool use."""

    def __init__(
            self,
            model_name: str,
            ollama_base_url: str,
            terminal_timeout_seconds: int = 45,
            model_timeout_seconds: int = 60,
    ) -> None:
        """Initialize agent model, tools, prompts, and scanner.

        Args:
            model_name: Ollama model name.
            ollama_base_url: Ollama server URL.
            terminal_timeout_seconds: Timeout for safe terminal tool.
            model_timeout_seconds: HTTP timeout for Ollama requests.
        """

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
        self._model = ChatOllama(
            model=model_name,
            base_url=ollama_base_url,
            temperature=0.1,
            client_kwargs={"timeout": max(5, model_timeout_seconds)},
        )
        self._agent = create_react_agent(
            model=self._model,
            tools=self._tools,
            prompt=self._system_prompt,
        )
        LOGGER.info(
            f"Prediction agent configured with Ollama model={model_name}, "
            f"tools={len(self._tools)}"
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
        prompt = self._build_user_prompt(
            source_file=markdown_path.name,
            match_label=match_label,
            signals=signals,
            dossier_markdown=markdown_text,
        )
        response_payload = self._agent.invoke(
            {"messages": [HumanMessage(content=prompt)]}
        )
        ai_content = self._extract_final_ai_content(payload=response_payload)
        parsed_prediction = self._parse_prediction_json(
            ai_content=ai_content,
            default_match=match_label,
            source_file=markdown_path.name,
        )
        LOGGER.info(
            f"Prediction completed [{markdown_path.name}] -> "
            f"{parsed_prediction.predicted_result} ({parsed_prediction.success_probability}%)"
        )
        return parsed_prediction

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

        line_match = re.search(r"^- Match:\s*(?P<value>.+)$", markdown_text, re.MULTILINE)
        if line_match is None:
            return "Unknown Match"
        return line_match.group("value").strip()

    @staticmethod
    def _extract_final_ai_content(payload: dict[str, Any]) -> str:
        """Extract final AI message text from LangGraph invocation payload."""

        messages = payload.get("messages")
        if not isinstance(messages, list):
            return ""
        ai_messages = [message for message in messages if isinstance(message, AIMessage)]
        if not ai_messages:
            fallback = [message for message in messages if isinstance(message, BaseMessage)]
            if not fallback:
                return ""
            return str(fallback[-1].content)
        last_message = ai_messages[-1]
        return str(last_message.content)

    def _parse_prediction_json(
            self,
            ai_content: str,
            default_match: str,
            source_file: str,
    ) -> PredictionResult:
        """Parse model output JSON into validated prediction object."""

        json_payload = self._extract_json_block(text=ai_content)
        if json_payload is None:
            return self._build_fallback_prediction(
                default_match=default_match,
                source_file=source_file,
                rationale=(
                    "The model did not return valid JSON output. "
                    f"Raw output: {ai_content[:1500]}"
                ),
            )
        try:
            parsed = PredictionResult.model_validate(
                {
                    **json_payload,
                    "match": json_payload.get("match") or default_match,
                    "source_file": source_file,
                    "outcome": "",
                }
            )
        except ValidationError as error:
            return self._build_fallback_prediction(
                default_match=default_match,
                source_file=source_file,
                rationale=(
                    "The model returned malformed JSON fields. "
                    f"Validation error: {error}. Raw JSON: {json.dumps(json_payload, ensure_ascii=False)}"
                ),
            )
        return parsed

    @staticmethod
    def _extract_json_block(text: str) -> dict[str, Any] | None:
        """Extract first JSON object from model text output."""

        match = JSON_BLOCK_PATTERN.search(text)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _build_fallback_prediction(
            default_match: str,
            source_file: str,
            rationale: str,
    ) -> PredictionResult:
        """Build conservative fallback prediction when parsing fails."""

        return PredictionResult(
            match=default_match,
            predicted_result="X",
            success_probability=50,
            rationale=rationale,
            evidence_refs=["fallback:no_valid_agent_json"],
            source_file=source_file,
            outcome="",
        )
