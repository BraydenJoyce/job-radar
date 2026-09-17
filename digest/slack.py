"""Delivers the digest as a single Slack message via an incoming webhook.

The message is built as Block Kit rather than plain text, because Adzuna's API
terms require their logo image and specific linked wording wherever their
listings and salary estimates are shown, and a plain text payload cannot carry
an image. See `_attribution_blocks`.
"""

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

    A predicted figure is Adzuna's own estimate, not the employer's, and their
    terms require it to be labelled "Adzuna Jobsworth" and linked. It is also
    simply less trustworthy, so the label does double duty.
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
    if predicted:
        text += f" · <{config.ADZUNA_JOBSWORTH_URL}|Adzuna Jobsworth>"
    return text


def format_digest(matches: Sequence[ScoredPosting]) -> str:
    """Plain text rendering, used as the notification fallback and by --no-slack."""
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


def _posting_block(m: ScoredPosting) -> dict:
    tag = TIER_LABELS.get(m.match_type, m.match_type.title())
    salary = format_salary(m.salary_min, m.salary_max, m.salary_is_predicted)
    meta = " · ".join(part for part in (m.location, salary) if part)
    meta = f"\n{meta}" if meta else ""
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"*<{m.url}|{m.title}>* at {m.company}\n"
                f"`{m.fit_score}` {tag}{meta}\n"
                f"_{m.reasoning}_"
            ),
        },
    }


def _attribution_blocks(matches: Sequence[ScoredPosting]) -> list[dict]:
    """Adzuna's required attribution, when the digest contains their listings.

    Their terms ask for the phrase "Jobs by Adzuna" with "Jobs" linked to the
    local Adzuna domain and "Adzuna" rendered as their logo image, also linked.
    Slack context blocks can carry an image element and linked mrkdwn, which is
    as close as a Slack message gets. Do not remove this: it is a condition of
    using their API, and it applies to anyone running this code.
    """
    if not any(m.source == "adzuna" for m in matches):
        return []

    elements: list[dict] = []
    if config.ADZUNA_LOGO_URL:
        elements.append(
            {
                "type": "image",
                "image_url": config.ADZUNA_LOGO_URL,
                "alt_text": "Adzuna",
            }
        )
    else:
        log.warning(
            "ADZUNA_LOGO_URL is not set, so the digest carries text attribution "
            "only. Adzuna's terms ask for their logo image; get the URL from "
            "https://www.adzuna.co.uk/press.html and set it in config.py."
        )

    elements.append(
        {
            "type": "mrkdwn",
            "text": (
                f"<{config.ADZUNA_SITE_URL}|Jobs> by "
                f"<{config.ADZUNA_SITE_URL}|Adzuna> · "
                f"salary estimates by <{config.ADZUNA_JOBSWORTH_URL}|Adzuna Jobsworth>"
            ),
        }
    )

    return [{"type": "divider"}, {"type": "context", "elements": elements}]


def build_blocks(matches: Sequence[ScoredPosting]) -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Job Radar: today's top matches"},
        }
    ]
    blocks.extend(_posting_block(m) for m in matches)
    blocks.extend(_attribution_blocks(matches))
    return blocks


def send_slack_digest(matches: Sequence[ScoredPosting], webhook_url: str | None = None) -> bool:
    """Post the digest. Returns False if nothing was sent."""
    if not matches:
        log.info("No matches today, sending nothing")
        return False

    webhook_url = webhook_url or config.SLACK_WEBHOOK_URL
    if not webhook_url:
        log.error("SLACK_WEBHOOK_URL is not set, cannot send digest")
        return False

    payload = {
        # `text` is the notification preview and the fallback for any client
        # that cannot render blocks.
        "text": format_digest(matches),
        "blocks": build_blocks(matches),
    }

    try:
        response = httpx.post(
            webhook_url, json=payload, timeout=config.HTTP_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("Slack delivery failed: %s", exc)
        return False

    log.info("Sent %d matches to Slack", len(matches))
    return True
