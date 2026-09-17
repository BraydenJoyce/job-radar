"""Shared data models.

`Posting` is the common shape every source normalizes into, so the dedup,
filter, scoring, and digest steps never care where a job came from.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

import config

MatchType = Literal["ideal", "strong", "bridge", "weak"]


def classify(fit_score: int) -> MatchType:
    """Map a fit score onto its band.

    Deriving the label instead of asking the model for it is the whole point:
    a 72 can never come back labelled "ideal", no matter how the prompt drifts.
    """
    for label, minimum in sorted(
        config.MATCH_TIER_THRESHOLDS.items(), key=lambda kv: kv[1], reverse=True
    ):
        if fit_score >= minimum:
            return label  # type: ignore[return-value]
    return "weak"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_PUNCTUATION = re.compile(r"[^a-z0-9]+")


def dedup_key(title: str, company: str) -> str:
    """Identify the same job listed many times over.

    Boards syndicate one opening across every state it is open in, so the same
    role arrives with a dozen posting ids and a dozen locations. Title plus
    company collapses them; location is deliberately excluded, because it is
    the only thing that differs.
    """
    def normalize(text: str) -> str:
        return _PUNCTUATION.sub(" ", text.lower()).strip()

    return f"{normalize(title)}|{normalize(company)}"


class Posting(BaseModel):
    """One job posting, normalized across sources."""

    posting_id: str  # "{source}:{native id}" -- stable across runs
    source: str
    title: str
    company: str
    location: Optional[str] = None
    url: str
    description: str
    posted_at: Optional[str] = None  # ISO 8601, None when a source omits it
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    # Adzuna estimates a salary when the employer does not state one. An
    # estimate is worth showing but not worth trusting, so it is flagged.
    salary_is_predicted: bool = False
    first_seen_at: str = Field(default_factory=utc_now_iso)
    passed_pre_filter: bool = True


class FitScore(BaseModel):
    """The scorer's structured verdict on a single posting.

    This is the schema the model is constrained to, so it holds only what the
    model actually judges. `match_type` is derived from the score.
    """

    fit_score: int = Field(ge=0, le=100)
    reasoning: str

    @property
    def match_type(self) -> MatchType:
        return classify(self.fit_score)


class ScoredPosting(BaseModel):
    """A posting joined to its score, ready for ranking and the digest."""

    posting_id: str
    title: str
    company: str
    location: Optional[str] = None
    url: str
    fit_score: int
    match_type: MatchType
    reasoning: str
    scored_at: str
    posted_at: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_is_predicted: bool = False
