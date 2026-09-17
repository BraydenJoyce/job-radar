"""Renders a digest to the terminal.

Slack is the intended destination, but requiring a Slack workspace to see any
output at all is a steep first step. This is what `--demo` and `--no-slack`
print, and it is enough to run the whole tool without Slack if you prefer.
"""

from __future__ import annotations

import os
import sys
from typing import Sequence

import config
from models import ScoredPosting, is_staffing_agency

# Colour is skipped when output is redirected, when NO_COLOR is set (the
# informal cross-tool convention), or on a terminal that will not handle it.
_USE_COLOR = (
    sys.stdout.isatty()
    and os.environ.get("NO_COLOR") is None
    and os.environ.get("TERM") != "dumb"
)


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


BAND_COLORS = {
    "ideal": "1;32",   # bold green
    "strong": "32",    # green
    "bridge": "33",    # yellow
    "weak": "90",      # grey
}

BAND_LABELS = {
    "ideal": "IDEAL FIT",
    "strong": "STRONG",
    "bridge": "BRIDGE",
    "weak": "WEAK",
}


def _salary(m: ScoredPosting) -> str:
    if not m.salary_min and not m.salary_max:
        return ""
    low, high = m.salary_min or m.salary_max, m.salary_max or m.salary_min
    text = (
        f"${round(low / 1000):,}k"
        if round(low) == round(high)
        else f"${round(low / 1000):,}k-${round(high / 1000):,}k"
    )
    # Adzuna's terms require their estimates to be identified as Jobsworth
    # wherever they are shown, terminal included.
    return f"{text} (Adzuna Jobsworth)" if m.salary_is_predicted else text


def render(matches: Sequence[ScoredPosting]) -> str:
    if not matches:
        return _c("Nothing cleared the bar today.", "90")

    width = 78
    lines = [
        _c("Job Radar", "1;36") + _c(" - today's top matches", "36"),
        _c("=" * width, "90"),
        "",
    ]

    for m in matches:
        band = _c(BAND_LABELS.get(m.match_type, m.match_type.upper()), BAND_COLORS.get(m.match_type, "0"))
        lines.append(f"  {_c(str(m.fit_score).rjust(3), '1')}  {band}  {_c(m.title, '1')}")
        lines.append(f"       {m.company}")

        agency = "via staffing agency" if is_staffing_agency(m.company) else ""
        meta = " · ".join(part for part in (m.location, _salary(m), agency) if part)
        if meta:
            lines.append(_c(f"       {meta}", "90"))

        # Wrap the reason rather than letting it run off the edge.
        words, line = m.reasoning.split(), "      "
        for word in words:
            if len(line) + len(word) + 1 > width:
                lines.append(_c(line, "3"))
                line = "      "
            line += f" {word}"
        if line.strip():
            lines.append(_c(line, "3"))

        lines.append(_c(f"       {m.url}", "94"))
        lines.append("")

    if any(m.source == "adzuna" for m in matches):
        lines.append(_c("-" * width, "90"))
        lines.append(
            _c(
                f"Jobs by Adzuna ({config.ADZUNA_SITE_URL}) · "
                f"salary estimates by Adzuna Jobsworth",
                "90",
            )
        )

    return "\n".join(lines)
