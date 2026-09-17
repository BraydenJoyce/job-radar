"""Deterministic filters applied before any AI budget is spent.

Everything here is free and local. A posting that fails is stored with
`passed_pre_filter = 0` so it is never fetched into the pipeline again, but it
is never deleted -- that record is what keeps it from being re-evaluated.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Iterable, Optional, Sequence

import config
from models import Posting

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilterResult:
    passed: bool
    reason: Optional[str] = None


@lru_cache(maxsize=16)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Word-boundary alternation, so "AI" does not match "maintenance".

    Cached on the term tuple rather than built once at import, so editing a
    list in config -- switching CAREER_LEVEL, most of all -- takes effect
    without a reimport. Compiling per call would otherwise cost real time
    across a few hundred postings.
    """
    escaped = sorted((re.escape(k.strip()) for k in keywords if k.strip()), key=len, reverse=True)
    if not escaped:
        # An empty term list must match nothing, not everything.
        return re.compile(r"(?!)")
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)


def _pattern_for(keywords: Iterable[str]) -> re.Pattern[str]:
    return _keyword_pattern(tuple(keywords))


def check(posting: Posting, now: Optional[datetime] = None) -> FilterResult:
    """Decide whether a posting is worth paying to score."""
    now = now or datetime.now(timezone.utc)

    if not _pattern_for(config.TITLE_KEYWORDS).search(posting.title):
        return FilterResult(False, "title has no target keyword")

    excluded = _pattern_for(config.EXCLUDED_TITLE_TERMS).search(posting.title)
    if excluded:
        return FilterResult(False, f"excluded title: {excluded.group(0).lower()}")

    haystack = f"{posting.title}\n{posting.description}"
    blocked = _pattern_for(config.BLOCKED_TERMS).search(haystack)
    if blocked:
        return FilterResult(False, f"requires credential: {blocked.group(0).lower()}")

    if posting.posted_at:
        try:
            posted = datetime.fromisoformat(posting.posted_at)
        except ValueError:
            posted = None
        if posted is not None:
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            age = now - posted
            if age > timedelta(days=config.MAX_POSTING_AGE_DAYS):
                return FilterResult(False, f"older than {config.MAX_POSTING_AGE_DAYS} days")

    # A missing posted_at is not grounds for discarding: several sources simply
    # do not report one, and first_seen_at bounds the staleness anyway.
    return FilterResult(True)


def apply(postings: Sequence[Posting], now: Optional[datetime] = None) -> list[Posting]:
    """Stamp `passed_pre_filter` on each posting and return them all."""
    now = now or datetime.now(timezone.utc)
    kept = 0
    for posting in postings:
        result = check(posting, now)
        posting.passed_pre_filter = result.passed
        if result.passed:
            kept += 1
        else:
            log.debug("Pre filter dropped %s (%s)", posting.posting_id, result.reason)
    log.info("Pre filter kept %d of %d postings", kept, len(postings))
    return list(postings)
