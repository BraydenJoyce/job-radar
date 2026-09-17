"""Job Radar daily entry point: fetch -> dedup -> pre filter -> score -> digest.

Usage:
    python scripts/run_daily.py                 # the full pipeline
    python scripts/run_daily.py --dry-run       # fetch and filter, no API spend
    python scripts/run_daily.py --no-slack      # score, but print instead of sending
    python scripts/run_daily.py --sources adzuna usajobs
    python scripts/run_daily.py --stats         # what is in the database
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow `python scripts/run_daily.py` from anywhere without installing a package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from db.repository import Repository
from digest import ranker, slack
from filtering import pre_filter
from models import Posting
from scoring import scorer
from scoring.claude_client import ScoringError
from sources import (
    adzuna_client,
    greenhouse_client,
    lever_client,
    usajobs_client,
)

log = logging.getLogger("job_radar")

FETCHERS = {
    "adzuna": adzuna_client.fetch,
    "usajobs": usajobs_client.fetch,
    "greenhouse": greenhouse_client.fetch,
    "lever": lever_client.fetch,
}


def fetch_all(sources: list[str]) -> list[Posting]:
    postings: list[Posting] = []
    for name in sources:
        fetcher = FETCHERS.get(name)
        if fetcher is None:
            log.warning("Unknown source %r, skipping", name)
            continue
        try:
            found = fetcher()
        except Exception as exc:  # one broken source must not kill the run
            log.exception("Source %r raised: %s", name, exc)
            continue
        log.info("Source %s returned %d postings", name, len(found))
        postings.extend(found)
    return postings


SOURCE_CREDENTIALS = {
    "adzuna": lambda: bool(config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY),
    "usajobs": lambda: bool(config.USAJOBS_API_KEY and config.USAJOBS_USER_AGENT),
    # Greenhouse and Lever need no keys, only a company list.
    "greenhouse": lambda: True,
    "lever": lambda: True,
}


def preflight(sources: list[str], dry_run: bool) -> list[str]:
    """Problems that would make this run pointless rather than merely empty.

    Without this, an unconfigured run fetches nothing, scores nothing, and
    reports "nothing cleared the bar today" -- indistinguishable from a quiet
    day, and it exits 0.
    """
    problems: list[str] = []

    usable = [s for s in sources if SOURCE_CREDENTIALS.get(s, lambda: True)()]
    if not usable:
        problems.append(
            f"No usable source: {', '.join(sources)} enabled, but none has credentials."
        )

    if not dry_run:
        if not config.ANTHROPIC_API_KEY:
            problems.append("ANTHROPIC_API_KEY is not set, so nothing can be scored.")
        if not config.PROFILE_PATH.exists():
            problems.append(
                f"{config.PROFILE_PATH.name} not found. Copy profile.example.txt to it."
            )

    return problems


def run(sources: list[str], dry_run: bool = False, send: bool = True) -> int:
    problems = preflight(sources, dry_run)
    if problems:
        for problem in problems:
            log.error("%s", problem)
        log.error("Run `python scripts/check_setup.py` for the full picture.")
        return 1

    with Repository() as repo:
        repo.init_schema()

        # 1. Fetch
        fetched = fetch_all(sources)
        if not fetched:
            log.warning("No postings fetched -- check credentials and queries")

        # 2. Dedup against everything ever seen
        fresh = repo.new_postings(fetched)
        log.info("%d new postings (%d already seen)", len(fresh), len(fetched) - len(fresh))

        # 3. Pre filter, then store the verdict so it is never re-evaluated
        pre_filter.apply(fresh)
        repo.insert_postings(fresh)

        if dry_run:
            kept = [p for p in fresh if p.passed_pre_filter]
            log.info("Dry run: %d postings would be scored", len(kept))
            for posting in kept[:20]:
                log.info("  %s at %s (%s)", posting.title, posting.company, posting.source)
            return 0

        # 4. Score
        try:
            scorer.score_pending(repo)
        except ScoringError as exc:
            log.error("Scoring could not run: %s", exc)
            return 1

        # 5. Rank and send
        matches = ranker.todays_digest(repo)
        if not matches:
            log.info("Nothing cleared the bar today, no digest sent")
            return 0

        if send:
            if slack.send_slack_digest(matches):
                repo.record_digest([m.posting_id for m in matches])
        else:
            print(slack.format_digest(matches))

    return 0


def show_stats() -> int:
    with Repository() as repo:
        repo.init_schema()
        for key, value in repo.counts().items():
            print(f"{key:>18}: {value}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Job Radar daily pipeline.")
    parser.add_argument(
        "--sources",
        nargs="+",
        default=config.ENABLED_SOURCES,
        choices=sorted(FETCHERS),
        help=f"Sources to fetch from (default: {' '.join(config.ENABLED_SOURCES)})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and pre filter only. Never calls the Claude API.",
    )
    parser.add_argument(
        "--no-slack",
        action="store_true",
        help="Score and rank, but print the digest instead of sending it.",
    )
    parser.add_argument("--stats", action="store_true", help="Print database counts and exit.")
    parser.add_argument("--verbose", action="store_true", help="Debug level logging.")
    args = parser.parse_args()

    config.setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    if args.stats:
        return show_stats()
    return run(args.sources, dry_run=args.dry_run, send=not args.no_slack)


if __name__ == "__main__":
    raise SystemExit(main())
