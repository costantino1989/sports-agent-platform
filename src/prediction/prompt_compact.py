"""Compact a rendered dossier before sending it to the prediction model.

The section 6 play-by-play can be hundreds of rows and dominates the prompt,
slowing the model or causing timeouts. This keeps every section intact but trims
section 6's event table to the most recent events. Everything else is untouched,
so the full dossier on disk stays complete for the record and the UI.
"""

from __future__ import annotations

SECTION_4_PREFIX = "## 4."
SECTION_6_PREFIX = "## 6."
SECTION_8_PREFIX = "## 8."
SECTION_PREFIX = "## "


def _strip_section(markdown: str, section_prefix: str) -> str:
    """Remove a whole ``## N.`` section (up to the next section) from the text.

    Returns the markdown unchanged when the section is absent.
    """

    lines = markdown.split("\n")
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(section_prefix)), None
    )
    if start is None:
        return markdown
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].startswith(SECTION_PREFIX)
        ),
        len(lines),
    )
    return "\n".join(lines[:start] + lines[end:])


def _section_bounds(
    lines: list[str], prefix: str = SECTION_6_PREFIX
) -> tuple[int, int] | None:
    """Return (start, end) line indices of the section, or None if absent."""

    start = next(
        (i for i, line in enumerate(lines) if line.startswith(prefix)), None
    )
    if start is None:
        return None
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].startswith(SECTION_PREFIX)
        ),
        len(lines),
    )
    return start, end


def has_team_statistics(markdown: str) -> bool:
    """Return whether section 4 carries real live team statistics.

    A match ESPN covers with a boxscore has numeric stats here even before any
    play-by-play event is logged (a quiet 0-0). This lets the live loop predict
    such matches on the stats plus the score/time baseline instead of skipping
    them for an empty event timeline.

    Args:
        markdown: Full rendered dossier markdown.

    Returns:
        True when section 4 exists, is not a "No data found" placeholder, and has
        at least one numeric table data row.
    """

    lines = markdown.split("\n")
    bounds = _section_bounds(lines, SECTION_4_PREFIX)
    if bounds is None:
        return False
    start, end = bounds
    section_lines = lines[start:end]
    if any("No data found" in line for line in section_lines):
        return False
    table_rows = [line for line in section_lines if line.startswith("|")]
    data_rows = table_rows[2:]  # drop header and separator
    return any(any(char.isdigit() for char in row) for row in data_rows)


def has_play_by_play(markdown: str, min_events: int = 1) -> bool:
    """Return whether section 6 carries at least ``min_events`` play-by-play rows.

    Used to deprioritize matches in competitions ESPN does not cover with live
    play-by-play (their dossier is too thin for a useful prediction).

    Args:
        markdown: Full rendered dossier markdown.
        min_events: Minimum number of event rows required.

    Returns:
        True when section 6 has at least ``min_events`` table data rows.
    """

    lines = markdown.split("\n")
    bounds = _section_bounds(lines)
    if bounds is None:
        return False
    start, end = bounds
    table_rows = [line for line in lines[start:end] if line.startswith("|")]
    # Drop the header and separator rows; the rest are events.
    data_rows = max(0, len(table_rows) - 2)
    return data_rows >= min_events


def compact_dossier_for_model(markdown: str, max_events: int) -> str:
    """Trim section 6's play-by-play table to the most recent events.

    Args:
        markdown: Full rendered dossier markdown.
        max_events: Maximum number of event rows to keep in section 6.

    Returns:
        The dossier with the odds section removed and section 6 trimmed, or with
        just the odds removed when there is no oversized play-by-play table.
    """

    # Hide the odds section entirely: the model predicts on stats + play-by-play,
    # not the market price (avoids anchoring). The file on disk keeps section 8,
    # which the betting layer reads separately.
    markdown = _strip_section(markdown, SECTION_8_PREFIX)
    lines = markdown.split("\n")
    bounds = _section_bounds(lines)
    if bounds is None:
        return markdown
    start, end = bounds
    section = lines[start:end]

    table_positions = [i for i, line in enumerate(section) if line.startswith("|")]
    if len(table_positions) <= 2:
        return markdown  # no table or header-only
    header, separator = table_positions[0], table_positions[1]
    data_positions = table_positions[2:]
    if len(data_positions) <= max_events:
        return markdown

    total = len(data_positions)
    kept = data_positions[-max_events:]
    note = f"_(mostrati gli ultimi {max_events} di {total} eventi della cronaca)_"

    rebuilt = (
        section[:header]
        + [note, "", section[header], section[separator]]
        + [section[i] for i in kept]
    )
    tail_start = data_positions[-1] + 1
    rebuilt += section[tail_start:]

    return "\n".join(lines[:start] + rebuilt + lines[end:])
