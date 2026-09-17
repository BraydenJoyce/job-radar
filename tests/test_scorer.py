import re

import pytest
from pydantic import ValidationError

import config
from models import FitScore, Posting
from scoring.claude_client import ClaudeScorer, ScoringError

PROFILE = "Jordan Rivera. Data analyst targeting analytics and business intelligence roles."


def make_posting(**overrides) -> Posting:
    defaults = dict(
        posting_id="adzuna:42",
        source="adzuna",
        title="Competitive Intelligence Analyst",
        company="Doosan Bobcat",
        location="West Fargo, ND",
        url="https://example.com/jobs/42",
        description="Track competitors and brief executives.",
    )
    defaults.update(overrides)
    return Posting(**defaults)


class FakeResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed


class FakeMessages:
    """Stands in for client.messages, replaying a queue of scripted outcomes."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


class FakeClient:
    def __init__(self, outcomes):
        self.messages = FakeMessages(outcomes)


def test_score_returns_validated_result():
    expected = FitScore(fit_score=88, reasoning="Direct match.")
    scorer = ClaudeScorer(client=FakeClient([expected]))

    result = scorer.score(PROFILE, make_posting())

    assert result.fit_score == 88


def test_request_uses_configured_model_and_schema():
    scorer = ClaudeScorer(
        client=FakeClient([FitScore(fit_score=50, reasoning="Maybe.")])
    )
    scorer.score(PROFILE, make_posting())

    call = scorer.client.messages.calls[0]
    assert call["model"] == config.SCORING_MODEL
    assert call["output_format"] is FitScore
    assert call["max_tokens"] == config.SCORING_MAX_TOKENS


def test_prompt_includes_profile_and_posting():
    scorer = ClaudeScorer(
        client=FakeClient([FitScore(fit_score=50, reasoning="Maybe.")])
    )
    posting = make_posting()
    prompt = scorer.build_prompt(PROFILE, posting)

    assert PROFILE in prompt
    assert posting.title in prompt
    assert posting.company in prompt
    # The rubric, not a label, is what the model is asked to apply.
    assert "90-100" in prompt and "60-74" in prompt


def test_long_description_is_truncated_before_it_is_sent():
    posting = make_posting(description="x" * (config.DESCRIPTION_CHAR_LIMIT + 5000))
    scorer = ClaudeScorer(
        client=FakeClient([FitScore(fit_score=50, reasoning="Maybe.")])
    )

    prompt = scorer.build_prompt(PROFILE, posting)

    assert "[description truncated]" in prompt
    # Measure the filler run itself -- incidental "x"s elsewhere in the
    # prompt (e.g. the word "exceed" in the rubric) must not count.
    longest_run = max(len(run) for run in re.findall(r"x+", prompt))
    assert longest_run == config.DESCRIPTION_CHAR_LIMIT


def test_retries_once_then_succeeds():
    good = FitScore(fit_score=71, reasoning="Close enough.")
    scorer = ClaudeScorer(client=FakeClient([ScoringError("bad json"), good]))

    result = scorer.score(PROFILE, make_posting())

    assert result.fit_score == 71
    assert len(scorer.client.messages.calls) == 2


def test_gives_up_after_the_retry():
    outcomes = [ScoringError("bad json")] * (config.SCORING_RETRIES + 1)
    scorer = ClaudeScorer(client=FakeClient(outcomes))

    with pytest.raises(ScoringError):
        scorer.score(PROFILE, make_posting())

    assert len(scorer.client.messages.calls) == config.SCORING_RETRIES + 1


def test_missing_parsed_output_is_treated_as_a_failure():
    good = FitScore(fit_score=60, reasoning="Fine.")
    scorer = ClaudeScorer(client=FakeClient([None, good]))

    assert scorer.score(PROFILE, make_posting()).fit_score == 60


@pytest.mark.parametrize(
    "payload",
    [
        {"fit_score": 101, "reasoning": "Too high."},
        {"fit_score": -1, "reasoning": "Too low."},
        {"fit_score": "high", "reasoning": "Not a number."},
    ],
)
def test_out_of_range_scores_do_not_validate(payload):
    with pytest.raises(ValidationError):
        FitScore(**payload)


def test_model_cannot_set_the_label_itself():
    """The band is computed, so a model that volunteers a label is ignored."""
    score = FitScore(fit_score=72, reasoning="Decent.", match_type="ideal")

    assert score.match_type == "bridge"
