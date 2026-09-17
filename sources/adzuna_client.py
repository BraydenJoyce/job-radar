"""Adzuna search API. Free key, broad US coverage -- the phase 1 source."""

from __future__ import annotations

import logging
from typing import Any, Iterable

import httpx

import config
from models import Posting
from sources.base import clean_text, to_iso

log = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"
SOURCE = "adzuna"


def fetch(
    queries: Iterable[str] | None = None,
    location: str | None = None,
    results_per_query: int | None = None,
) -> list[Posting]:
    """Fetch one page of results for each search query."""
    if not config.ADZUNA_APP_ID or not config.ADZUNA_APP_KEY:
        log.warning("Adzuna credentials missing, skipping source")
        return []

    queries = list(queries if queries is not None else config.SEARCH_QUERIES)
    location = config.SEARCH_LOCATION if location is None else location
    per_query = results_per_query or config.RESULTS_PER_QUERY

    postings: list[Posting] = []
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SECONDS) as client:
        for query in queries:
            params: dict[str, Any] = {
                "app_id": config.ADZUNA_APP_ID,
                "app_key": config.ADZUNA_APP_KEY,
                "what": query,
                "results_per_page": min(per_query, 50),  # Adzuna's page cap
                "max_days_old": config.MAX_POSTING_AGE_DAYS,
                "content-type": "application/json",
            }
            if location:
                params["where"] = location

            found = 0
            for page in range(1, config.ADZUNA_PAGES + 1):
                try:
                    response = client.get(BASE_URL.format(page=page), params=params)
                    response.raise_for_status()
                    results = response.json().get("results", [])
                except httpx.HTTPError as exc:
                    log.error("Adzuna query %r page %d failed: %s", query, page, exc)
                    break
                except ValueError as exc:
                    log.error("Adzuna query %r page %d returned invalid JSON: %s", query, page, exc)
                    break

                for result in results:
                    posting = _to_posting(result)
                    if posting is not None:
                        postings.append(posting)
                found += len(results)

                # A short page is the last page; asking for the next one just
                # spends a request to get nothing back.
                if len(results) < params["results_per_page"]:
                    break

            log.info("Adzuna %r: %d results", query, found)

    return postings


def _to_posting(result: dict[str, Any]) -> Posting | None:
    native_id = result.get("id")
    url = result.get("redirect_url")
    title = result.get("title")
    if not native_id or not url or not title:
        log.debug("Skipping malformed Adzuna result: %s", result.get("id"))
        return None

    return Posting(
        posting_id=f"{SOURCE}:{native_id}",
        source=SOURCE,
        title=clean_text(title),
        company=clean_text((result.get("company") or {}).get("display_name")) or "Unknown",
        location=clean_text((result.get("location") or {}).get("display_name")) or None,
        url=url,
        description=clean_text(result.get("description")),
        posted_at=to_iso(result.get("created")),
        salary_min=result.get("salary_min"),
        salary_max=result.get("salary_max"),
        salary_is_predicted=bool(int(result.get("salary_is_predicted") or 0)),
    )
