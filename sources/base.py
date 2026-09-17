"""Helpers shared by every source client."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]*\n\s*\n\s*", re.MULTILINE)


def clean_text(raw: Optional[str]) -> str:
    """Strip HTML tags and entities out of a job description.

    Sources return wildly different markup. Descriptions are what the scorer
    pays for by the token, so tags are dead weight as well as noise.
    """
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)  # entities can survive one pass inside tags
    text = _WHITESPACE_RE.sub("\n\n", text)
    return text.strip()


def to_iso(value: object) -> Optional[str]:
    """Normalize the assorted date shapes sources return into ISO 8601 UTC."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # Lever hands back epoch milliseconds.
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        for parse in (
            lambda t: datetime.fromisoformat(t),
            lambda t: datetime.strptime(t, "%Y-%m-%d"),
            lambda t: datetime.strptime(t, "%m/%d/%Y"),
        ):
            try:
                parsed = parse(text)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        log.debug("Could not parse date %r", value)
    return None
