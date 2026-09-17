"""Recompute every stored match_type from its fit score.

Labels are derived from `config.MATCH_TIER_THRESHOLDS`, so moving a threshold
changes what new postings are called but leaves old rows on the old labels.
Run this after editing the thresholds to bring history back in step. It reads
and writes only the `scores` table and never calls the API.

    python scripts/relabel_scores.py --dry-run
    python scripts/relabel_scores.py
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from db.repository import Repository
from models import classify


def relabel(dry_run: bool = False) -> int:
    with Repository() as repo:
        repo.init_schema()
        rows = repo.conn.execute(
            "SELECT posting_id, fit_score, match_type FROM scores"
        ).fetchall()

        changes = [
            (row["posting_id"], row["match_type"], classify(row["fit_score"]))
            for row in rows
        ]
        changed = [c for c in changes if c[1] != c[2]]

        print(f"{len(rows)} scored postings, {len(changed)} need a new label")
        for old, new in sorted(Counter((c[1], c[2]) for c in changed).items()):
            print(f"  {old[0]:>6} -> {old[1]:<6} {new:>4}")

        if not changed:
            return 0
        if dry_run:
            print("\nDry run, nothing written.")
            return 0

        repo.conn.executemany(
            "UPDATE scores SET match_type = ? WHERE posting_id = ?",
            [(new, pid) for pid, _old, new in changed],
        )
        repo.conn.commit()
        print(f"\nUpdated {len(changed)} rows.")

        after = repo.conn.execute(
            "SELECT match_type, COUNT(*) n FROM scores GROUP BY match_type"
        ).fetchall()
        print("Now:", ", ".join(f"{r['match_type']}={r['n']}" for r in after))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show changes only.")
    args = parser.parse_args()
    raise SystemExit(relabel(dry_run=args.dry_run))
