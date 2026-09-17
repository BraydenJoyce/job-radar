"""Companies whose Greenhouse / Lever boards get checked every day.

A slug is the company's identifier in the board URL, for example
`https://boards.greenhouse.io/stripe` -> "stripe", and
`https://jobs.lever.co/netflix` -> "netflix".

Start with 10 to 20 companies you have already applied to or want to watch, and
add to these lists over time. A bad slug just logs a 404 and is skipped, so a
wrong guess never breaks a run.
"""

from __future__ import annotations

GREENHOUSE_COMPANIES: list[str] = [
    # "stripe",
    # "databricks",
]

LEVER_COMPANIES: list[str] = [
    # "netflix",
    # "plaid",
]
