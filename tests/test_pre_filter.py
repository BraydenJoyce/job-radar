from datetime import datetime, timedelta, timezone

import pytest

import config
from filtering import pre_filter
from models import Posting

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def make_posting(**overrides) -> Posting:
    defaults = dict(
        posting_id="adzuna:1",
        source="adzuna",
        title="Data Analyst",
        company="Acme Industrial",
        location="Fargo, ND",
        url="https://example.com/jobs/1",
        description="Build dashboards and analyze operational data.",
        posted_at=(NOW - timedelta(days=2)).isoformat(),
    )
    defaults.update(overrides)
    return Posting(**defaults)


@pytest.mark.parametrize(
    "title",
    [
        "Data Analyst",
        "AI Engineer",
        "Competitive Intelligence Analyst",
        "Machine Learning Engineer",
        "Strategy Associate",
        "Market Research Associate",
        "Analytics Manager",
    ],
)
def test_target_titles_pass(title):
    assert pre_filter.check(make_posting(title=title), NOW).passed


@pytest.mark.parametrize(
    "title",
    [
        "Line Cook",
        "Maintenance Technician",  # contains "ai" but not as a word
        "Retail Sales Associate",  # contains "ai" inside "Retail"
        "Registered Dental Hygienist",
    ],
)
def test_off_target_titles_are_dropped(title):
    result = pre_filter.check(make_posting(title=title), NOW)
    assert not result.passed
    assert result.reason == "title has no target keyword"


def test_clearance_requirement_is_dropped():
    posting = make_posting(
        description="Applicants must hold an active TS/SCI security clearance."
    )
    result = pre_filter.check(posting, NOW)
    assert not result.passed
    assert "credential" in result.reason


def test_unrelated_license_is_dropped():
    posting = make_posting(
        title="Clinical Data Analyst",
        description="Current registered nurse credentials required.",
    )
    assert not pre_filter.check(posting, NOW).passed


def test_stale_postings_are_dropped():
    old = (NOW - timedelta(days=config.MAX_POSTING_AGE_DAYS + 1)).isoformat()
    result = pre_filter.check(make_posting(posted_at=old), NOW)
    assert not result.passed
    assert "older than" in result.reason


def test_posting_on_the_age_boundary_is_kept():
    edge = (NOW - timedelta(days=config.MAX_POSTING_AGE_DAYS)).isoformat()
    assert pre_filter.check(make_posting(posted_at=edge), NOW).passed


def test_missing_posted_at_is_kept():
    # Several sources omit a date entirely; that is not a reason to discard.
    assert pre_filter.check(make_posting(posted_at=None), NOW).passed


def test_unparseable_posted_at_is_kept():
    assert pre_filter.check(make_posting(posted_at="not a date"), NOW).passed


def test_apply_stamps_every_posting():
    postings = [
        make_posting(posting_id="a", title="Data Analyst"),
        make_posting(posting_id="b", title="Line Cook"),
    ]
    result = pre_filter.apply(postings, NOW)
    assert len(result) == 2
    assert result[0].passed_pre_filter is True
    assert result[1].passed_pre_filter is False


@pytest.mark.parametrize(
    "title",
    [
        "Senior Data Analyst",
        "Sr. Data Analyst",
        "Lead AI Engineer",
        "Director, AI Engineering",
        "Staff AI Engineer",
        "Principal Data Scientist",
        "VP of Analytics",
        "Head of Data Strategy",
        "Chief Data Officer",
    ],
)
def test_senior_titles_are_dropped_before_scoring(title):
    result = pre_filter.check(make_posting(title=title), NOW)
    assert not result.passed
    assert result.reason.startswith("excluded title:")


@pytest.mark.parametrize(
    "title",
    ["Data Analyst", "AI Engineer", "Competitive Intelligence Analyst", "Analytics Manager"],
)
def test_non_senior_titles_survive(title):
    # "Manager" is deliberately not an excluded term -- the title spans too
    # wide a range of seniority to reject on sight.
    assert pre_filter.check(make_posting(title=title), NOW).passed


def test_seniority_is_judged_on_the_title_only():
    # "senior leadership" in the body of a description is not a seniority signal.
    posting = make_posting(
        title="Data Analyst",
        description="You will present findings to senior leadership weekly.",
    )
    assert pre_filter.check(posting, NOW).passed


@pytest.mark.parametrize(
    "title",
    [
        "Machine Learning Engineer - Summer Intern 2027",
        "2027 Intern - Digital Strategy Analyst",
        "Data Analyst Internship",
        "Data Analytics Co-op",
        "Summer Interns - Research Analyst",
    ],
)
def test_internships_are_dropped(title):
    result = pre_filter.check(make_posting(title=title), NOW)
    assert not result.passed
    assert result.reason.startswith("excluded title:")


@pytest.mark.parametrize(
    "title",
    [
        "Internal Audit Analyst",       # "intern" inside "Internal"
        "International Data Analyst",   # "intern" inside "International"
    ],
)
def test_intern_exclusion_does_not_catch_similar_words(title):
    assert pre_filter.check(make_posting(title=title), NOW).passed
