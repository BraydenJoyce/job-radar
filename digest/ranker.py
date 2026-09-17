"""Picks what actually goes in today's Slack message."""

from __future__ import annotations

import logging
from typing import Sequence

import config
from db.repository import Repository
from models import ScoredPosting, dedup_key, is_staffing_agency

log = logging.getLogger(__name__)


def rank(
    candidates: Sequence[ScoredPosting],
    size: int | None = None,
    min_score: int | None = None,
) -> list[ScoredPosting]:
    """Highest fit score first, capped, with a quality floor.

    A short, high quality list gets read. A long one gets ignored, which is
    the failure mode this whole tool exists to avoid.
    """
    size = config.DIGEST_SIZE if size is None else size
    min_score = config.MIN_DIGEST_SCORE if min_score is None else min_score

    qualified = [c for c in candidates if c.fit_score >= min_score]
    # Scores bunch up hard -- a dozen postings can share a 72 -- so the
    # tie-break decides most of the digest. Freshest first; a posting with no
    # date sorts last rather than winning by accident.
    # Not tie-broken on match_type: it is derived from the score, so postings
    # that tie on score always share a label.
    def sort_key(c: ScoredPosting) -> tuple[int, str]:
        # Agencies advertise a client's role, and several will carry the same
        # job. The penalty applies to ordering only -- the stored fit score is
        # about fit, and stays honest.
        effective = c.fit_score
        if is_staffing_agency(c.company):
            effective -= config.STAFFING_AGENCY_PENALTY
        return (effective, c.posted_at or "")

    ordered = sorted(qualified, key=sort_key, reverse=True)

    # Last line of defence against the same job filling several slots. The
    # fetch step already collapses syndicated listings, but rows stored before
    # that existed -- or a job listed under two sources -- would still slip
    # through, and here it costs a slot in the only output you read.
    selected: list[ScoredPosting] = []
    seen_keys: set[str] = set()
    for candidate in ordered:
        key = dedup_key(candidate.title, candidate.company)
        if key in seen_keys:
            log.debug("Skipping duplicate in digest: %s", candidate.posting_id)
            continue
        seen_keys.add(key)
        selected.append(candidate)
        if len(selected) == size:
            break
    return selected


def todays_digest(repo: Repository) -> list[ScoredPosting]:
    """Everything scored and not yet sent, ranked and cut to size."""
    candidates = repo.unsent_scored()
    selected = rank(candidates)
    log.info("Digest: %d of %d candidates selected", len(selected), len(candidates))
    return selected
