"""Delivers the digest as a single Slack message via an incoming webhook."""

from __future__ import annotations

import logging
from typing import Sequence

import httpx

import config
from models import ScoredPosting

log = logging.getLogger(__name__)

# How each band reads in Slack. The stored label is the short machine name;
# this is the human one.
TIER_LABELS = {
    "ideal": "Ideal fit",
    "strong": "Strong match",
    "bridge": "Bridge",
    "weak": "Weak fit",
}


def format_salary(
    minimum: float | None, maximum: float | None, predicted: bool
) -> str:
    """Render a salary range compactly, or nothing when there is no figure.

    Adzuna fills in an estimate when the employer states no salary, and an
    estimate reads identically to a real figure unless it is labelled.
    """
    if not minimum and not maximum:
        return ""

    def thousands(value: float) -> str:
        return f"${round(value / 1000):,}k"

    low, high = minimum or maximum, maximum or minimum
    text = (
        thousands(low)
        if round(low) == round(high)
        else f"{thousands(low)}-{thousands(high)}"
    )
    return f"{text} (est.)" if predicted else text


def format_digest(matches: Sequence[ScoredPosting]) -> str:
    lines = ["*Job Radar, today's top matches:*"]
    for m in matches:
        tag = TIER_LABELS.get(m.match_type, m.match_type.title())
        salary = format_salary(m.salary_min, m.salary_max, m.salary_is_predicted)
        meta = " · ".join(part for part in (m.location, salary) if part)
        meta = f" · {meta}" if meta else ""
        lines.append(
            f"[{m.fit_score}] *{tag}* — {m.title} at {m.company}{meta}\n"
            f"{m.url}\n_{m.reasoning}_"
        )
    return "\n\n".join(lines)


def send_slack_digest(matches: Sequence[ScoredPosting], webhook_url: str | None = None) -> bool:
    """Post the digest. Returns False if nothing was sent."""
    if not matches:
        log.info("No matches today, sending nothing")
        return False

    webhook_url = webhook_url or config.SLACK_WEBHOOK_URL
    if not webhook_url:
        log.error("SLACK_WEBHOOK_URL is not set, cannot send digest")
        return False

    text = format_digest(matches)
    try:
        response = httpx.post(
            webhook_url,
            json={"text": text},
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("Slack delivery failed: %s", exc)
        return False

    log.info("Sent %d matches to Slack", len(matches))
    return True
