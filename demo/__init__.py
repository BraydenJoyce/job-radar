"""Bundled sample data, so the pipeline can be run with no keys and no network.

The point is that someone can clone this repo and see a real digest before
deciding whether to sign up for four services. The postings here are genuine
listings fetched from Adzuna and USAJobs; the scores are genuine Claude output,
produced once against `profile.example.txt` and frozen.

The demo runs the *real* pipeline over them -- dedup, pre filter, ranking,
rendering -- and only the fetch and score steps are swapped for these fixtures.
So what you see is the actual behaviour, not a mock up.
"""

from __future__ import annotations

import json
from pathlib import Path

from models import FitScore, Posting

HERE = Path(__file__).resolve().parent
POSTINGS_PATH = HERE / "sample_postings.json"
SCORES_PATH = HERE / "sample_scores.json"


def load_postings() -> list[Posting]:
    """The bundled listings, deliberately including some the filter rejects."""
    raw = json.loads(POSTINGS_PATH.read_text(encoding="utf-8"))
    return [Posting(**item) for item in raw]


def load_scores() -> dict[str, FitScore]:
    raw = json.loads(SCORES_PATH.read_text(encoding="utf-8"))
    return {pid: FitScore(**value) for pid, value in raw.items()}


class DemoScorer:
    """Stands in for ClaudeScorer, returning frozen scores instead of calling the API.

    Same interface as the real scorer, so `scorer.score_pending` drives it
    without knowing the difference.
    """

    def __init__(self) -> None:
        self.scores = load_scores()
        self.calls = 0

    def score(self, profile: str, posting: Posting) -> FitScore:
        self.calls += 1
        score = self.scores.get(posting.posting_id)
        if score is None:
            # Every posting that passes the filter has a frozen score; a miss
            # means the two fixture files have drifted apart.
            raise KeyError(
                f"No demo score for {posting.posting_id}. "
                f"sample_postings.json and sample_scores.json are out of sync."
            )
        return score
