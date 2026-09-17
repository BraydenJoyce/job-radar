"""The one part of the pipeline that costs money.

A single Claude Haiku call per posting, constrained to a JSON schema so the
response is a validated `FitScore` rather than prose that has to be parsed.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import anthropic
from pydantic import ValidationError

import config
from models import FitScore, Posting

log = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are helping evaluate job postings against a candidate's background for personal job search use.

Candidate profile:
{profile}

Job posting:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Score this posting's fit for the candidate from 0 to 100 using this scale:

90-100: On the candidate's target trajectory. The core work is the kind they have already done, and their background covers most of the requirements. Worth applying to today.
75-89: A real fit with a clear gap. The work is genuinely relevant, but the seniority, domain, or required stack is a meaningful stretch or a partial mismatch.
60-74: Plausible near term income. The candidate could get it and do it well, but it does not advance the target trajectory.
40-59: Weak. Adjacent at best, or the requirements substantially exceed the candidate's background.
0-39: Not a fit.

{career_guidance}

Be strict. A role that merely shares a job title with the candidate's target, without the substance behind it, belongs in the 60s.

Give a precise score that uses the full range. Do not round to the nearest 5 or 10, and do not give the same score to two postings that differ in fit. Across a typical batch of 50 postings, expect roughly one at 85 or above, four from 75 to 84, twelve from 60 to 74, and the rest below 60.

Give a one sentence reason naming the single strongest fit or the single biggest gap."""


class ScoringError(RuntimeError):
    """Raised when a posting could not be scored after retrying."""


class ClaudeScorer:
    def __init__(self, client: Optional[anthropic.Anthropic] = None) -> None:
        if client is not None:
            self.client = client
        else:
            if not config.ANTHROPIC_API_KEY:
                raise ScoringError(
                    "ANTHROPIC_API_KEY is not set. Add it to .env before scoring."
                )
            self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def build_prompt(self, profile: str, posting: Posting) -> str:
        description = posting.description[: config.DESCRIPTION_CHAR_LIMIT]
        if len(posting.description) > config.DESCRIPTION_CHAR_LIMIT:
            description += "\n[description truncated]"

        try:
            career_guidance = config.CAREER_LEVEL_GUIDANCE[config.CAREER_LEVEL]
        except KeyError:
            raise ScoringError(
                f"CAREER_LEVEL is {config.CAREER_LEVEL!r}, which has no guidance. "
                f"Use one of: {', '.join(sorted(config.CAREER_LEVEL_GUIDANCE))}."
            ) from None

        return PROMPT_TEMPLATE.format(
            profile=profile.strip(),
            title=posting.title,
            company=posting.company,
            location=posting.location or "Not specified",
            description=description,
            career_guidance=career_guidance,
        )

    def score(self, profile: str, posting: Posting) -> FitScore:
        """Score one posting, retrying once if the response does not validate."""
        prompt = self.build_prompt(profile, posting)
        last_error: Exception | None = None

        for attempt in range(config.SCORING_RETRIES + 1):
            try:
                response = self.client.messages.parse(
                    model=config.SCORING_MODEL,
                    max_tokens=config.SCORING_MAX_TOKENS,
                    messages=[{"role": "user", "content": prompt}],
                    output_format=FitScore,
                    # The API honours temperature on Haiku, but the SDK
                    # dropped it from the typed signature, so it travels in
                    # extra_body. Without it the same posting can score 15
                    # points apart across runs.
                    extra_body={"temperature": config.SCORING_TEMPERATURE},
                )
                parsed = response.parsed_output
                if parsed is None:
                    raise ScoringError("model returned no parsed output")
                return parsed
            except (ValidationError, ScoringError, json.JSONDecodeError) as exc:
                last_error = exc
                log.warning(
                    "Unparseable score for %s (attempt %d): %s",
                    posting.posting_id,
                    attempt + 1,
                    exc,
                )
            except anthropic.NotFoundError as exc:
                # Bad model id or no access -- retrying will not help.
                raise ScoringError(f"model {config.SCORING_MODEL} unavailable: {exc}") from exc
            except anthropic.RateLimitError as exc:
                # The SDK already retried with backoff before raising.
                last_error = exc
                log.warning("Rate limited scoring %s: %s", posting.posting_id, exc)
            except anthropic.APIStatusError as exc:
                last_error = exc
                log.warning("API error scoring %s: %s", posting.posting_id, exc)
            except anthropic.APIConnectionError as exc:
                last_error = exc
                log.warning("Connection error scoring %s: %s", posting.posting_id, exc)

        raise ScoringError(
            f"could not score {posting.posting_id} after "
            f"{config.SCORING_RETRIES + 1} attempts: {last_error}"
        )
