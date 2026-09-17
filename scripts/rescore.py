"""Re-score postings that already have a score, using the current prompt.

Scores are only comparable to each other if they came from the same prompt and
the same profile. After editing either one, this brings history back in step.

Unlike `relabel_scores.py`, this one calls the API and costs money, so it
prints an estimate and requires --yes to actually spend.

    python scripts/rescore.py                 # estimate only
    python scripts/rescore.py --yes           # rescore everything scored
    python scripts/rescore.py --limit 20 --yes
    python scripts/rescore.py --min-score 60 --yes
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from db.repository import Repository, _row_to_posting
from models import classify
from scoring.claude_client import ClaudeScorer, ScoringError
from scoring.scorer import load_profile

# Haiku 4.5 rates, used only for the pre-flight estimate.
INPUT_PER_MTOK = 1.00
OUTPUT_PER_MTOK = 5.00
EST_OUTPUT_TOKENS = 90


def estimate_cost(prompt_chars: int, count: int) -> float:
    input_tokens = prompt_chars / 4  # ~4 chars per token
    return (
        input_tokens / 1_000_000 * INPUT_PER_MTOK
        + count * EST_OUTPUT_TOKENS / 1_000_000 * OUTPUT_PER_MTOK
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Actually spend money.")
    parser.add_argument("--limit", type=int, help="Rescore at most this many.")
    parser.add_argument("--min-score", type=int, default=0, help="Only rescore at or above this score.")
    args = parser.parse_args()

    config.setup_logging()

    with Repository() as repo:
        repo.init_schema()
        sql = """
            SELECT p.*, s.fit_score AS old_score, s.match_type AS old_label
            FROM scores s JOIN postings p ON p.posting_id = s.posting_id
            WHERE s.fit_score >= ?
            ORDER BY s.fit_score DESC
        """
        params: list[object] = [args.min_score]
        if args.limit:
            sql += " LIMIT ?"
            params.append(args.limit)
        rows = repo.conn.execute(sql, params).fetchall()

        if not rows:
            print("Nothing to rescore.")
            return 0

        profile = load_profile()
        scorer = ClaudeScorer()
        prompt_chars = sum(
            len(scorer.build_prompt(profile, _row_to_posting(r))) for r in rows
        )
        cost = estimate_cost(prompt_chars, len(rows))
        print(f"{len(rows)} postings, estimated cost ${cost:.2f} at {config.SCORING_MODEL}")

        if not args.yes:
            print("Estimate only. Re-run with --yes to spend.")
            return 0

        moves: list[tuple[int, int, str]] = []
        failed = 0
        for i, row in enumerate(rows, 1):
            posting = _row_to_posting(row)
            try:
                result = scorer.score(profile, posting)
            except ScoringError as exc:
                failed += 1
                print(f"  [{i}/{len(rows)}] FAILED {posting.posting_id}: {exc}")
                continue
            repo.save_score(posting.posting_id, result)
            moves.append((row["old_score"], result.fit_score, posting.title))
            if i % 20 == 0:
                print(f"  ... {i}/{len(rows)}")

        up = sum(1 for o, n, _ in moves if n > o)
        down = sum(1 for o, n, _ in moves if n < o)
        same = sum(1 for o, n, _ in moves if n == o)
        print(f"\nRescored {len(moves)} ({failed} failed): {up} up, {down} down, {same} unchanged")

        biggest = sorted(moves, key=lambda m: abs(m[1] - m[0]), reverse=True)[:8]
        if biggest:
            print("\nBiggest moves:")
            for old, new, title in biggest:
                print(f"  {old:>3} -> {new:>3} ({new - old:+3})  {title[:52]}")

        bands = Counter(classify(n) for _, n, _ in moves)
        print("\nNew bands:", ", ".join(f"{k}={v}" for k, v in bands.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
