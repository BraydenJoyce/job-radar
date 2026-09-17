CREATE TABLE IF NOT EXISTS postings (
    posting_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    url TEXT NOT NULL,
    description TEXT NOT NULL,
    posted_at TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_is_predicted INTEGER,
    first_seen_at TEXT NOT NULL,
    passed_pre_filter INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS scores (
    posting_id TEXT PRIMARY KEY REFERENCES postings(posting_id),
    fit_score INTEGER NOT NULL,
    reasoning TEXT NOT NULL,
    match_type TEXT NOT NULL,
    scored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS digests (
    digest_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at TEXT NOT NULL,
    posting_ids TEXT NOT NULL
);

-- Supports the "what is waiting to be scored" query that runs every day.
CREATE INDEX IF NOT EXISTS idx_postings_pre_filter
    ON postings(passed_pre_filter);

CREATE INDEX IF NOT EXISTS idx_scores_scored_at
    ON scores(scored_at);
