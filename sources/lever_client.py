"""Lever public job board feeds. No key, one request per company."""

from __future__ import annotations

import logging
from typing import Any, Iterable

import httpx

import config
from models import Posting
from sources.base import clean_text, to_iso
from sources.watched_companies import LEVER_COMPANIES

log = logging.getLogger(__name__)

BASE_URL = "https://api.lever.co/v0/postings/{slug}"
SOURCE = "lever"


def fetch(companies: Iterable[str] | None = None) -> list[Posting]:
    slugs = list(companies if companies is not None else LEVER_COMPANIES)
    if not slugs:
        log.info("No Lever companies watched, skipping source")
        return []

    postings: list[Posting] = []
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SECONDS) as client:
        for slug in slugs:
            try:
                response = client.get(
                    BASE_URL.format(slug=slug), params={"mode": "json"}
                )
                response.raise_for_status()
                jobs = response.json()
            except httpx.HTTPError as exc:
                log.error("Lever board %r failed: %s", slug, exc)
                continue
            except ValueError as exc:
                log.error("Lever board %r returned invalid JSON: %s", slug, exc)
                continue

            if not isinstance(jobs, list):
                log.error("Lever board %r returned an unexpected shape", slug)
                continue

            for job in jobs:
                posting = _to_posting(job, slug)
                if posting is not None:
                    postings.append(posting)
            log.info("Lever %r: %d jobs", slug, len(jobs))

    return postings


def _to_posting(job: dict[str, Any], slug: str) -> Posting | None:
    native_id = job.get("id")
    title = job.get("text")
    url = job.get("hostedUrl") or job.get("applyUrl")
    if not native_id or not title or not url:
        return None

    categories = job.get("categories") or {}
    # descriptionPlain is already tag free; description is HTML. Lists of
    # responsibilities live in `lists`, which is where most of the detail is.
    body = job.get("descriptionPlain") or clean_text(job.get("description"))
    extra = "\n\n".join(
        f"{item.get('text', '')}\n{clean_text(item.get('content'))}"
        for item in (job.get("lists") or [])
    )

    return Posting(
        posting_id=f"{SOURCE}:{slug}:{native_id}",
        source=SOURCE,
        title=clean_text(title),
        company=slug.replace("-", " ").title(),
        location=clean_text(categories.get("location")) or None,
        url=url,
        description=clean_text(f"{body}\n\n{extra}"),
        posted_at=to_iso(job.get("createdAt")),
    )
