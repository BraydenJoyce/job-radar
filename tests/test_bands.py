import pytest

import config
from digest import ranker, slack
from models import FitScore, ScoredPosting, classify


@pytest.mark.parametrize(
    "score,expected",
    [
        (100, "ideal"),
        (72, "bridge"),  # the score that started this change
        (59, "weak"),
        (0, "weak"),
    ],
)
def test_bands(score, expected):
    assert classify(score) == expected


@pytest.mark.parametrize("label", sorted(config.MATCH_TIER_THRESHOLDS))
def test_each_threshold_is_inclusive(label):
    """A score exactly on a threshold earns that band; one point under does not."""
    minimum = config.MATCH_TIER_THRESHOLDS[label]

    assert classify(minimum) == label
    assert classify(minimum - 1) != label


def test_bands_follow_config():
    """Moving a threshold moves the label, with no other code change."""
    original = dict(config.MATCH_TIER_THRESHOLDS)
    try:
        config.MATCH_TIER_THRESHOLDS["ideal"] = 70
        assert classify(72) == "ideal"
    finally:
        config.MATCH_TIER_THRESHOLDS.clear()
        config.MATCH_TIER_THRESHOLDS.update(original)
    assert classify(72) == "bridge"


def make_scored(score: int) -> ScoredPosting:
    # Distinct title per score: the ranker dedups by title+company, so a
    # shared one would collapse the whole fixture into a single row.
    return ScoredPosting(
        posting_id=f"adzuna:{score}",
        title=f"Data Analyst {score}",
        company="Acme",
        location="Remote",
        url="https://example.com",
        fit_score=score,
        match_type=classify(score),
        reasoning="Because.",
        scored_at="2026-09-16T00:00:00+00:00",
    )


def test_weak_postings_never_reach_the_digest():
    candidates = [make_scored(s) for s in (95, 80, 65, 59, 30)]

    selected = ranker.rank(candidates)

    assert [c.fit_score for c in selected] == [95, 80, 65]
    assert all(c.match_type != "weak" for c in selected)


def test_slack_shows_the_band_name():
    text = slack.format_digest([make_scored(95), make_scored(80), make_scored(65)])

    assert "*Ideal fit*" in text
    assert "*Strong match*" in text
    assert "*Bridge*" in text


def make_named(score: int, title: str, company: str = "Acme") -> ScoredPosting:
    return ScoredPosting(
        posting_id=f"adzuna:{title}:{company}:{score}",
        title=title,
        company=company,
        location="Remote",
        url="https://example.com",
        fit_score=score,
        match_type=classify(score),
        reasoning="Because.",
        scored_at="2026-09-16T00:00:00+00:00",
    )


def test_digest_never_shows_the_same_job_twice():
    # Four copies of one BMO listing would otherwise eat half the digest.
    candidates = [make_named(72, "Credit Strategy Analyst III", "BMO") for _ in range(4)]
    candidates.append(make_named(68, "Data Analyst", "Globex"))

    selected = ranker.rank(candidates)

    assert len(selected) == 2
    assert [c.company for c in selected] == ["BMO", "Globex"]


def test_deduping_still_fills_the_digest():
    """Dropping a duplicate frees the slot for the next best posting."""
    candidates = [make_named(90, "Data Analyst", "Acme"), make_named(89, "Data Analyst", "Acme")]
    candidates += [make_named(80 - i, f"Role {i}", "Globex") for i in range(8)]

    selected = ranker.rank(candidates, size=8)

    assert len(selected) == 8
    assert sum(1 for c in selected if c.company == "Acme") == 1


@pytest.mark.parametrize(
    "minimum,maximum,predicted,expected",
    [
        (86000, 124000, False, "$86k-$124k"),
        (84102.55, 84102.55, True, "$84k (est.)"),
        (95000, None, False, "$95k"),
        (None, None, False, ""),
        (None, 110000, False, "$110k"),
    ],
)
def test_salary_formatting(minimum, maximum, predicted, expected):
    assert slack.format_salary(minimum, maximum, predicted) == expected


def test_digest_line_includes_salary_when_known():
    posting = make_named(82, "Data Analyst", "Acme")
    posting.salary_min, posting.salary_max = 86000, 124000

    text = slack.format_digest([posting])

    assert "$86k-$124k" in text


def test_digest_line_omits_salary_when_absent():
    text = slack.format_digest([make_named(82, "Data Analyst", "Acme")])

    assert "$" not in text


def test_ties_break_toward_the_fresher_posting():
    older = make_named(72, "Data Analyst", "Older Co")
    newer = make_named(72, "Data Analyst", "Newer Co")
    undated = make_named(72, "Data Analyst", "Undated Co")
    older.posted_at = "2026-09-01T00:00:00+00:00"
    newer.posted_at = "2026-09-15T00:00:00+00:00"

    selected = ranker.rank([older, undated, newer], size=3)

    assert [c.company for c in selected] == ["Newer Co", "Older Co", "Undated Co"]
