"""Greenhouse public job board feeds. No key, one request per company."""

from __future__ import annotations

import logging
from typing import Any, Iterable

import httpx

import config
from models import Posting
from sources.base import clean_text, to_iso
from sources.watched_companies import GREENHOUSE_COMPANIES

log = logging.getLogger(__name__)

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
SOURCE = "greenhouse"


def fetch(companies: Iterable[str] | None = None) -> list[Posting]:
    slugs = list(companies if companies is not None else GREENHOUSE_COMPANIES)
    if not slugs:
        log.info("No Greenhouse companies watched, skipping source")
        return []

    postings: list[Posting] = []
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SECONDS) as client:
        for slug in slugs:
            try:
                # content=true returns the full HTML description in the same call.
                response = client.get(
                    BASE_URL.format(slug=slug), params={"content": "true"}
                )
                response.raise_for_status()
                jobs = response.json().get("jobs", [])
            except httpx.HTTPError as exc:
                log.error("Greenhouse board %r failed: %s", slug, exc)
                continue
            except ValueError as exc:
                log.error("Greenhouse board %r returned invalid JSON: %s", slug, exc)
                continue

            for job in jobs:
                posting = _to_posting(job, slug)
                if posting is not None:
                    postings.append(posting)
            log.info("Greenhouse %r: %d jobs", slug, len(jobs))

    return postings


def _to_posting(job: dict[str, Any], slug: str) -> Posting | None:
    native_id = job.get("id")
    title = job.get("title")
    url = job.get("absolute_url")
    if not native_id or not title or not url:
        return None

    company = (job.get("company_name") or slug).replace("-", " ").title()
    location = (job.get("location") or {}).get("name")

    return Posting(
        posting_id=f"{SOURCE}:{slug}:{native_id}",
        source=SOURCE,
        title=clean_text(title),
        company=clean_text(company),
        location=clean_text(location) or None,
        url=url,
        description=clean_text(job.get("content")),
        posted_at=to_iso(job.get("updated_at") or job.get("first_published")),
    )
