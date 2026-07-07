"""Contract tests binding the dossier no-data line to the rule scanner.

The renderers and the prediction rule scanner must agree on the exact
"No data found" wording. A single shared template guarantees they cannot drift.
"""

from __future__ import annotations

from src.models.no_data import NO_DATA_TEMPLATE
from src.prediction.agents.rule_scan import DossierRuleScanner


def test_scanner_detects_rendered_no_data_line() -> None:
    rendered = NO_DATA_TEMPLATE.format(section="Injuries")
    signals = DossierRuleScanner().scan(markdown_text=rendered)
    no_data = [signal for signal in signals if signal.name == "explicit_no_data"]
    assert len(no_data) == 1
    assert no_data[0].triggered is True
    assert "Injuries" in no_data[0].details


def test_all_renderers_share_the_single_template() -> None:
    from src.dossier import render, render_context, render_flow

    assert render.NO_DATA_TEMPLATE is NO_DATA_TEMPLATE
    assert render_context.NO_DATA_TEMPLATE is NO_DATA_TEMPLATE
    assert render_flow.NO_DATA_TEMPLATE is NO_DATA_TEMPLATE
