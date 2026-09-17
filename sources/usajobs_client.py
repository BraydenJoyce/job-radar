"""USAJobs search API. Free, official, federal postings."""

from __future__ import annotations

import logging
from typing import Any, Iterable

import httpx

import config
from models import Posting
from sources.base import clean_text, to_iso

log = logging.getLogger(__name__)

BASE_URL = "https://data.usajobs.gov/api/search"
SOURCE = "usajobs"


def fetch(
    queries: Iterable[str] | None = None,
    location: str | None = None,
    results_per_query: int | None = None,
) -> list[Posting]:
    if not config.USAJOBS_API_KEY or not config.USAJOBS_USER_AGENT:
        log.warning("USAJobs credentials missing, skipping source")
        return []

    queries = list(queries if queries is not None else config.SEARCH_QUERIES)
    location = config.SEARCH_LOCATION if location is None else location
    per_query = results_per_query or config.RESULTS_PER_QUERY

    headers = {
        "Host": "data.usajobs.gov",
        # USAJobs requires the email address the key was registered with.
        "User-Agent": config.USAJOBS_USER_AGENT,
        "Authorization-Key": config.USAJOBS_API_KEY,
    }

    postings: list[Posting] = []
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SECONDS, headers=headers) as client:
        for query in queries:
            params: dict[str, Any] = {
                "Keyword": query,
                "ResultsPerPage": min(per_query, 500),
                "DatePosted": config.MAX_POSTING_AGE_DAYS,  # max 60
            }
            if location:
                params["LocationName"] = location

            try:
                response = client.get(BASE_URL, params=params)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPError as exc:
                log.error("USAJobs query %r failed: %s", query, exc)
                continue
            except ValueError as exc:
                log.error("USAJobs query %r returned invalid JSON: %s", query, exc)
                continue

            items = payload.get("SearchResult", {}).get("SearchResultItems", [])
            for item in items:
                posting = _to_posting(item.get("MatchedObjectDescriptor", {}))
                if posting is not None:
                    postings.append(posting)
            log.info("USAJobs %r: %d results", query, len(items))

    return postings


def _to_posting(descriptor: dict[str, Any]) -> Posting | None:
    native_id = descriptor.get("PositionID")
    title = descriptor.get("PositionTitle")
    url = descriptor.get("PositionURI")
    if not native_id or not title or not url:
        return None

    locations = descriptor.get("PositionLocationDisplay") or ", ".join(
        loc.get("LocationName", "")
        for loc in descriptor.get("PositionLocation", [])
        if loc.get("LocationName")
    )

    # The summary lives in a nested list; qualifications add the detail the
    # scorer actually needs to judge fit.
    details = descriptor.get("UserArea", {}).get("Details", {})
    parts = [
        descriptor.get("QualificationSummary"),
        details.get("JobSummary"),
        details.get("MajorDuties"),
    ]
    description = clean_text("\n\n".join(str(p) for p in parts if p))

    return Posting(
        posting_id=f"{SOURCE}:{native_id}",
        source=SOURCE,
        title=clean_text(title),
        company=clean_text(descriptor.get("OrganizationName")) or "US Federal Government",
        location=clean_text(locations) or None,
        url=url,
        description=description,
        posted_at=to_iso(descriptor.get("PublicationStartDate")),
    )
