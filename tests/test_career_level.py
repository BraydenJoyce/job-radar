"""Career level is the setting a new user must change first, so it gets the
most direct tests: switching it has to change both what is filtered for free
and how the scorer is told to weigh seniority."""

import contextlib

import pytest

import config
from filtering import pre_filter
from models import Posting
from scoring.claude_client import ClaudeScorer, ScoringError


@contextlib.contextmanager
def career_level(level: str):
    """Temporarily switch career level, rebuilding the derived term list."""
    original_level = config.CAREER_LEVEL
    original_terms = config.EXCLUDED_TITLE_TERMS
    config.CAREER_LEVEL = level
    config.EXCLUDED_TITLE_TERMS = (
        config.SENIORITY_EXCLUSIONS[level] + config.ALWAYS_EXCLUDED_TITLE_TERMS
    )
    try:
        yield
    finally:
        config.CAREER_LEVEL = original_level
        config.EXCLUDED_TITLE_TERMS = original_terms


def make_posting(title: str) -> Posting:
    return Posting(
        posting_id="adzuna:1",
        source="adzuna",
        title=title,
        company="Acme",
        location="Remote",
        url="https://example.com/1",
        description="Analyze data.",
    )


def test_every_level_has_matching_filters_and_guidance():
    """A level with one but not the other would silently half-work."""
    assert set(config.SENIORITY_EXCLUSIONS) == set(config.CAREER_LEVEL_GUIDANCE)
    assert config.CAREER_LEVEL in config.SENIORITY_EXCLUSIONS


def test_early_career_drops_senior_titles():
    with career_level("early"):
        assert not pre_filter.check(make_posting("Senior Data Analyst")).passed
        assert not pre_filter.check(make_posting("Lead Data Analyst")).passed


def test_senior_career_keeps_senior_titles():
    with career_level("senior"):
        assert pre_filter.check(make_posting("Senior Data Analyst")).passed
        assert pre_filter.check(make_posting("Staff Data Analyst")).passed
        assert pre_filter.check(make_posting("Principal Data Analyst")).passed


def test_mid_career_keeps_senior_but_drops_executives():
    with career_level("mid"):
        assert pre_filter.check(make_posting("Senior Data Analyst")).passed
        assert not pre_filter.check(make_posting("Director of Data")).passed


@pytest.mark.parametrize("level", ["early", "mid", "senior"])
def test_internships_are_dropped_at_every_level(level):
    with career_level(level):
        assert not pre_filter.check(make_posting("Data Analyst Intern")).passed


@pytest.mark.parametrize("level", ["early", "mid", "senior"])
def test_prompt_carries_that_levels_guidance(level):
    scorer = ClaudeScorer.__new__(ClaudeScorer)  # no client needed to build a prompt
    with career_level(level):
        prompt = scorer.build_prompt("A candidate.", make_posting("Data Analyst"))

    assert config.CAREER_LEVEL_GUIDANCE[level] in prompt
    for other in config.CAREER_LEVEL_GUIDANCE:
        if other != level:
            assert config.CAREER_LEVEL_GUIDANCE[other] not in prompt


def test_unknown_career_level_fails_loudly():
    scorer = ClaudeScorer.__new__(ClaudeScorer)
    original = config.CAREER_LEVEL
    config.CAREER_LEVEL = "principal-staff-wizard"
    try:
        with pytest.raises(ScoringError, match="CAREER_LEVEL"):
            scorer.build_prompt("A candidate.", make_posting("Data Analyst"))
    finally:
        config.CAREER_LEVEL = original


# --- preflight -------------------------------------------------------------
# An unconfigured run used to fetch nothing, score nothing, report "nothing
# cleared the bar today" and exit 0, which is indistinguishable from a quiet
# day. These pin the loud failure.

import importlib

run_daily = importlib.import_module("scripts.run_daily")


@contextlib.contextmanager
def credentials(**overrides):
    originals = {k: getattr(config, k) for k in overrides}
    for key, value in overrides.items():
        setattr(config, key, value)
    try:
        yield
    finally:
        for key, value in originals.items():
            setattr(config, key, value)


def test_preflight_flags_a_source_with_no_credentials():
    with credentials(ADZUNA_APP_ID="", ADZUNA_APP_KEY=""):
        problems = run_daily.preflight(["adzuna"], dry_run=True)

    assert any("No usable source" in p for p in problems)


def test_preflight_flags_a_missing_api_key_for_a_real_run():
    with credentials(ADZUNA_APP_ID="x", ADZUNA_APP_KEY="y", ANTHROPIC_API_KEY=""):
        problems = run_daily.preflight(["adzuna"], dry_run=False)

    assert any("ANTHROPIC_API_KEY" in p for p in problems)


def test_dry_run_does_not_need_an_api_key_or_profile():
    """--dry-run never scores, so it must stay usable before those exist."""
    with credentials(ADZUNA_APP_ID="x", ADZUNA_APP_KEY="y", ANTHROPIC_API_KEY=""):
        assert run_daily.preflight(["adzuna"], dry_run=True) == []


def test_a_configured_run_has_no_problems(tmp_path):
    profile = tmp_path / "profile.txt"
    profile.write_text("A candidate.", encoding="utf-8")
    with credentials(
        ADZUNA_APP_ID="x", ADZUNA_APP_KEY="y",
        ANTHROPIC_API_KEY="sk-test", PROFILE_PATH=profile,
    ):
        assert run_daily.preflight(["adzuna"], dry_run=False) == []


def test_unconfigured_run_exits_nonzero():
    with credentials(ADZUNA_APP_ID="", ADZUNA_APP_KEY="", ANTHROPIC_API_KEY=""):
        assert run_daily.run(["adzuna"], dry_run=True) == 1
