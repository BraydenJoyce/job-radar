"""Drives scoring across every posting that is waiting for one."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from db.repository import Repository
from scoring.claude_client import ClaudeScorer, ScoringError

log = logging.getLogger(__name__)


@dataclass
class ScoringRun:
    scored: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


def load_profile(path: Path | str = config.PROFILE_PATH) -> str:
    """Read profile.txt fresh on every run, so edits take effect immediately."""
    path = Path(path)
    if not path.exists():
        # profile.txt is gitignored, so this is what a fresh clone hits first.
        raise ScoringError(
            f"{path.name} not found. Copy profile.example.txt to {path.name} and "
            f"replace it with your own background -- it is what every posting is "
            f"scored against."
        )
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ScoringError(f"{path} is empty -- the scorer has nothing to compare against")
    return text


def score_pending(
    repo: Repository,
    scorer: ClaudeScorer | None = None,
    limit: int | None = None,
) -> ScoringRun:
    """Score every unscored posting that passed the pre filter."""
    limit = config.MAX_SCORE_PER_RUN if limit is None else limit
    pending = repo.unscored_postings(limit=limit)
    if not pending:
        log.info("Nothing to score")
        return ScoringRun()

    profile = load_profile()
    scorer = scorer or ClaudeScorer()
    run = ScoringRun()

    log.info("Scoring %d postings with %s", len(pending), config.SCORING_MODEL)
    for posting in pending:
        try:
            result = scorer.score(profile, posting)
        except ScoringError as exc:
            # A posting that fails stays unscored and is retried tomorrow.
            run.failed += 1
            run.failures.append(posting.posting_id)
            log.error("Skipping %s: %s", posting.posting_id, exc)
            continue

        repo.save_score(posting.posting_id, result)
        run.scored += 1
        log.info(
            "[%3d] %-6s %s at %s",
            result.fit_score,
            result.match_type,
            posting.title[:60],
            posting.company[:30],
        )

    log.info("Scored %d postings, %d failed", run.scored, run.failed)
    return run
