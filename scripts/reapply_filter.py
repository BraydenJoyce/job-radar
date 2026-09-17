"""Re-run the pre filter over postings already in the database.

The pre filter normally runs once, when a posting is first stored. Editing
`EXCLUDED_TITLE_TERMS`, `TITLE_KEYWORDS`, or `BLOCKED_TERMS` therefore only
affects postings fetched afterwards -- anything already stored keeps the
verdict it was given under the old rules, and a previously scored posting can
still reach the digest.

This re-applies the current rules to every stored posting. It does not call the
API and does not delete anything; it only updates `passed_pre_filter`.

    python scripts/reapply_filter.py --dry-run
    python scripts/reapply_filter.py
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from db.repository import Repository, _row_to_posting
from filtering import pre_filter


def reapply(dry_run: bool = False) -> int:
    with Repository() as repo:
        repo.init_schema()
        rows = repo.conn.execute("SELECT * FROM postings").fetchall()

        newly_failed: list[tuple[str, str, str]] = []
        newly_passed: list[tuple[str, str]] = []
        for row in rows:
            posting = _row_to_posting(row)
            result = pre_filter.check(posting)
            was = bool(row["passed_pre_filter"])
            if was and not result.passed:
                newly_failed.append((posting.posting_id, posting.title, result.reason or ""))
            elif not was and result.passed:
                newly_passed.append((posting.posting_id, posting.title))

        print(f"{len(rows)} stored postings")
        print(f"  now fail the filter: {len(newly_failed)}")
        print(f"  now pass the filter: {len(newly_passed)}")

        if newly_failed:
            print("\n  Newly excluded, by reason:")
            for reason, n in Counter(r.split(":")[0] for _, _, r in newly_failed).most_common():
                print(f"    {reason:24} {n}")
            print("\n  Examples:")
            for _, title, reason in newly_failed[:8]:
                print(f"    {title[:52]:52} ({reason})")

        if dry_run:
            print("\nDry run, nothing written.")
            return 0
        if not newly_failed and not newly_passed:
            print("\nNothing to change.")
            return 0

        repo.conn.executemany(
            "UPDATE postings SET passed_pre_filter = 0 WHERE posting_id = ?",
            [(pid,) for pid, _, _ in newly_failed],
        )
        repo.conn.executemany(
            "UPDATE postings SET passed_pre_filter = 1 WHERE posting_id = ?",
            [(pid,) for pid, _ in newly_passed],
        )
        repo.conn.commit()
        print(f"\nUpdated {len(newly_failed) + len(newly_passed)} rows.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show changes only.")
    args = parser.parse_args()
    raise SystemExit(reapply(dry_run=args.dry_run))
