import tempfile
from pathlib import Path

import pytest

import config
from db.repository import Repository
from models import Posting, dedup_key


@pytest.fixture
def repo():
    with tempfile.TemporaryDirectory() as tmp:
        r = Repository(Path(tmp) / "test.db")
        r.init_schema(config.SCHEMA_PATH)
        yield r
        r.close()


def make_posting(pid: str, title: str = "Data Analyst", company: str = "Acme", location: str = "Remote") -> Posting:
    return Posting(
        posting_id=pid,
        source="adzuna",
        title=title,
        company=company,
        location=location,
        url=f"https://example.com/{pid}",
        description="Analyze data.",
    )


def test_dedup_key_ignores_case_punctuation_and_spacing():
    assert dedup_key("Lead AI Engineer", "Accurate Background") == dedup_key(
        "LEAD  AI  ENGINEER!", "accurate background"
    )


def test_dedup_key_separates_different_companies():
    assert dedup_key("Data Analyst", "Acme") != dedup_key("Data Analyst", "Globex")


def test_same_job_syndicated_across_states_is_kept_once(repo):
    batch = [
        make_posting(f"adzuna:{i}", location=state)
        for i, state in enumerate(["Ohio", "Texas", "Florida", "Maine"])
    ]

    fresh = repo.new_postings(batch)

    assert len(fresh) == 1
    assert fresh[0].posting_id == "adzuna:0"


def test_duplicates_stay_filtered_on_the_next_run(repo):
    repo.insert_postings(repo.new_postings([make_posting("adzuna:1", location="Ohio")]))

    # Tomorrow the board serves the whole spread again, including a new id.
    again = repo.new_postings(
        [make_posting("adzuna:1", location="Ohio"), make_posting("adzuna:2", location="Texas")]
    )

    assert again == []


def test_genuinely_different_jobs_are_both_kept(repo):
    batch = [
        make_posting("adzuna:1", title="Data Analyst"),
        make_posting("adzuna:2", title="AI Engineer"),
        make_posting("adzuna:3", title="Data Analyst", company="Globex"),
    ]

    assert len(repo.new_postings(batch)) == 3


def test_previously_seen_ids_are_dropped(repo):
    repo.insert_postings(repo.new_postings([make_posting("adzuna:1")]))

    assert repo.new_postings([make_posting("adzuna:1")]) == []
