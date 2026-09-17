"""The demo is the first thing a stranger runs, so it has to work on a clone
with no .env, no profile.txt and no network. These pin that."""

import json

import pytest

import demo
from filtering import pre_filter


def test_fixtures_load():
    postings = demo.load_postings()
    assert len(postings) > 10
    assert all(p.title and p.company and p.url for p in postings)


def test_every_posting_that_passes_the_filter_has_a_score():
    """The two fixture files drifting apart would break the demo silently."""
    postings = demo.load_postings()
    scores = demo.load_scores()

    for posting in postings:
        if pre_filter.check(posting).passed:
            assert posting.posting_id in scores, f"no demo score for {posting.title}"


def test_fixtures_include_postings_the_filter_rejects():
    """The demo should show the filter working, not just the survivors."""
    postings = demo.load_postings()
    rejected = [p for p in postings if not pre_filter.check(p).passed]

    assert rejected, "bundle some postings that get filtered out"


def test_demo_scorer_returns_frozen_scores():
    postings = demo.load_postings()
    scorer = demo.DemoScorer()
    scored = next(p for p in postings if p.posting_id in scorer.scores)

    result = scorer.score("any profile", scored)

    assert 0 <= result.fit_score <= 100
    assert result.reasoning
    assert scorer.calls == 1


def test_demo_scorer_is_loud_when_fixtures_drift():
    scorer = demo.DemoScorer()
    postings = demo.load_postings()
    orphan = postings[0].model_copy(update={"posting_id": "nope:1"})

    with pytest.raises(KeyError, match="out of sync"):
        scorer.score("any profile", orphan)


def test_demo_makes_no_network_calls(monkeypatch):
    """Guard the promise in the README: the demo costs nothing."""
    import httpx

    def explode(*args, **kwargs):
        raise AssertionError("the demo must not make network calls")

    monkeypatch.setattr(httpx, "post", explode)
    monkeypatch.setattr(httpx, "get", explode)

    scorer = demo.DemoScorer()
    for posting in demo.load_postings():
        if posting.posting_id in scorer.scores:
            scorer.score("any profile", posting)

    assert scorer.calls > 0


def test_scores_are_valid_json_and_in_range():
    raw = json.loads(demo.SCORES_PATH.read_text(encoding="utf-8"))
    for pid, value in raw.items():
        assert 0 <= value["fit_score"] <= 100, pid
        assert value["reasoning"].strip(), pid
