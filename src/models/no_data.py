"""Shared 'no data' contract for dossier renderers and the rule scanner.

Both the markdown renderers (which emit the line) and the prediction rule
scanner (which detects it) import from here, so the wording and its matching
regex cannot drift apart.
"""

from __future__ import annotations

import re

NO_DATA_TEMPLATE = (
    "No data found (source: ESPN API, section: {section}). "
    "Suggested action: verify via web search."
)

# Detects a rendered no-data line and captures the section name.
NO_DATA_SECTION_PATTERN = re.compile(
    r"No data found \(source: ESPN API, section: (?P<section>.+?)\)\."
)
