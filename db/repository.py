"""SQLite persistence for postings, scores, and sent digests.

The database is the dedup memory of the whole system: a posting that has been
seen once is never fetched into the pipeline again, and a posting that has been
sent once never reappears in Slack.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

import config
from models import FitScore, Posting, ScoredPosting, dedup_key, utc_now_iso

log = logging.getLogger(__name__)


class Repository:
    def __init__(self, db_path: Path | str = config.DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    # --- schema ------------------------------------------------------------

    def init_schema(self, schema_path: Path | str = config.SCHEMA_PATH) -> None:
        sql = Path(schema_path).read_text(encoding="utf-8")
        self.conn.executescript(sql)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns that `CREATE TABLE IF NOT EXISTS` cannot add.

        The schema file only describes a fresh database. A database created
        before a column existed keeps its old shape, so each new column has to
        be added here too.
        """
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(postings)")}
        for column, ddl in (
            ("salary_min", "REAL"),
            ("salary_max", "REAL"),
            ("salary_is_predicted", "INTEGER"),
        ):
            if column not in existing:
                self.conn.execute(f"ALTER TABLE postings ADD COLUMN {column} {ddl}")
                log.info("Added column postings.%s", column)

    # --- postings ----------------------------------------------------------

    def known_ids(self, posting_ids: Iterable[str]) -> set[str]:
        """Which of these posting_ids are already in the database."""
        ids = list(posting_ids)
        if not ids:
            return set()
        found: set[str] = set()
        # Chunked to stay under SQLite's variable limit on big fetch days.
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            placeholders = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"SELECT posting_id FROM postings WHERE posting_id IN ({placeholders})",
                chunk,
            ).fetchall()
            found.update(row["posting_id"] for row in rows)
        return found

    def existing_dedup_keys(self) -> set[str]:
        rows = self.conn.execute("SELECT title, company FROM postings").fetchall()
        return {dedup_key(row["title"], row["company"]) for row in rows}

    def new_postings(self, postings: Sequence[Posting]) -> list[Posting]:
        """Drop anything already stored, by id and by content.

        The id check catches a posting seen on a previous run. The content
        check catches the same opening syndicated across a dozen state
        listings, which arrives as a dozen distinct ids for one job.

        Content duplicates are dropped rather than stored: leaving them out
        costs nothing on the next run, because the one copy that was kept
        already blocks the whole group by content.
        """
        seen_ids = self.known_ids(p.posting_id for p in postings)
        seen_keys = self.existing_dedup_keys()

        fresh: list[Posting] = []
        duplicates = 0
        for posting in postings:
            if posting.posting_id in seen_ids:
                continue
            key = dedup_key(posting.title, posting.company)
            if key in seen_keys:
                duplicates += 1
                continue
            seen_ids.add(posting.posting_id)
            seen_keys.add(key)
            fresh.append(posting)

        if duplicates:
            log.info("Dropped %d duplicate listings of the same job", duplicates)
        return fresh

    def insert_postings(self, postings: Sequence[Posting]) -> int:
        """Insert postings, ignoring any that raced in already."""
        if not postings:
            return 0
        rows = [
            (
                p.posting_id,
                p.source,
                p.title,
                p.company,
                p.location,
                p.url,
                p.description,
                p.posted_at,
                p.salary_min,
                p.salary_max,
                int(p.salary_is_predicted),
                p.first_seen_at,
                int(p.passed_pre_filter),
            )
            for p in postings
        ]
        cur = self.conn.executemany(
            """
            INSERT OR IGNORE INTO postings (
                posting_id, source, title, company, location, url,
                description, posted_at, salary_min, salary_max,
                salary_is_predicted, first_seen_at, passed_pre_filter
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.commit()
        return cur.rowcount

    def unscored_postings(self, limit: int | None = None) -> list[Posting]:
        """Postings that passed the pre filter and have no score yet."""
        sql = """
            SELECT p.* FROM postings p
            LEFT JOIN scores s ON s.posting_id = p.posting_id
            WHERE p.passed_pre_filter = 1 AND s.posting_id IS NULL
            ORDER BY p.first_seen_at DESC
        """
        params: list[object] = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [_row_to_posting(row) for row in rows]

    # --- scores ------------------------------------------------------------

    def save_score(self, posting_id: str, score: FitScore) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO scores (
                posting_id, fit_score, reasoning, match_type, scored_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                posting_id,
                score.fit_score,
                score.reasoning,
                score.match_type,
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def unsent_scored(self, max_age_days: int = config.DIGEST_CANDIDATE_DAYS) -> list[ScoredPosting]:
        """Scored postings that have never gone out in a digest.

        Deliberately not limited to postings scored today: one that missed the
        cut because yesterday was crowded is still a valid candidate. The
        `digests` table is what guarantees a posting is only ever sent once,
        and `max_age_days` stops stale near-misses from competing forever.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max_age_days)
        ).isoformat()
        rows = self.conn.execute(
            """
            SELECT p.posting_id, p.source, p.title, p.company, p.location, p.url,
                   p.posted_at, p.salary_min, p.salary_max,
                   COALESCE(p.salary_is_predicted, 0) AS salary_is_predicted,
                   s.fit_score, s.match_type, s.reasoning, s.scored_at
            FROM scores s
            JOIN postings p ON p.posting_id = s.posting_id
            WHERE p.first_seen_at >= ? AND p.passed_pre_filter = 1
            ORDER BY s.fit_score DESC
            """,
            (cutoff,),
        ).fetchall()
        # `digests` stores a comma separated list per send, so the already-sent
        # filter happens here rather than in SQL.
        already_sent = self.sent_posting_ids()
        return [
            ScoredPosting(**dict(row))
            for row in rows
            if row["posting_id"] not in already_sent
        ]

    # --- digests -----------------------------------------------------------

    def record_digest(self, posting_ids: Sequence[str]) -> None:
        if not posting_ids:
            return
        self.conn.execute(
            "INSERT INTO digests (sent_at, posting_ids) VALUES (?, ?)",
            (utc_now_iso(), ",".join(posting_ids)),
        )
        self.conn.commit()

    def sent_posting_ids(self) -> set[str]:
        rows = self.conn.execute("SELECT posting_ids FROM digests").fetchall()
        sent: set[str] = set()
        for row in rows:
            sent.update(pid for pid in row["posting_ids"].split(",") if pid)
        return sent

    # --- stats -------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        def one(sql: str) -> int:
            return int(self.conn.execute(sql).fetchone()[0])

        return {
            "postings": one("SELECT COUNT(*) FROM postings"),
            "passed_pre_filter": one(
                "SELECT COUNT(*) FROM postings WHERE passed_pre_filter = 1"
            ),
            "scored": one("SELECT COUNT(*) FROM scores"),
            "digests": one("SELECT COUNT(*) FROM digests"),
        }


def _row_to_posting(row: sqlite3.Row) -> Posting:
    return Posting(
        posting_id=row["posting_id"],
        source=row["source"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        url=row["url"],
        description=row["description"],
        posted_at=row["posted_at"],
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        salary_is_predicted=bool(row["salary_is_predicted"] or 0),
        first_seen_at=row["first_seen_at"],
        passed_pre_filter=bool(row["passed_pre_filter"]),
    )
