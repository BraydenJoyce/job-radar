"""Check that Job Radar is configured, before it tries to spend anything.

Run this first on a new checkout. It verifies the things that otherwise fail
one at a time, halfway through a run: missing keys, a missing profile, an
unwritable database, a career level with no matching guidance.

Nothing here calls a paid API. With --live it makes one free Adzuna request and
one USAJobs request to confirm the credentials actually authenticate, which
neither provider charges for.

    python scripts/check_setup.py
    python scripts/check_setup.py --live
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK, WARN, FAIL = "  ok  ", " warn ", " FAIL "

_results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    _results.append((status, name, detail))


def check_python() -> None:
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 11):
        record(OK, "Python version", f"{major}.{minor}")
    else:
        record(FAIL, "Python version", f"{major}.{minor}, need 3.11 or newer")


def check_imports() -> None:
    missing = []
    for module in ("httpx", "pydantic", "dotenv", "anthropic"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        record(FAIL, "Dependencies", f"missing {', '.join(missing)} -- pip install -r requirements.txt")
    else:
        record(OK, "Dependencies", "all importable")


def check_config() -> None:
    import config

    env_path = config.ROOT / ".env"
    if env_path.exists():
        record(OK, ".env", "present")
    else:
        record(FAIL, ".env", "not found -- copy .env.example to .env and fill it in")

    # Anthropic is the only hard requirement: without it nothing can be scored.
    if config.ANTHROPIC_API_KEY:
        record(OK, "ANTHROPIC_API_KEY", "set")
    else:
        record(FAIL, "ANTHROPIC_API_KEY", "not set -- required for scoring (console.anthropic.com)")

    if config.SLACK_WEBHOOK_URL:
        record(OK, "SLACK_WEBHOOK_URL", "set")
    else:
        record(WARN, "SLACK_WEBHOOK_URL", "not set -- scoring works, delivery does not")

    enabled = config.ENABLED_SOURCES
    if "adzuna" in enabled:
        if config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY:
            record(OK, "Adzuna credentials", "set")
        else:
            record(FAIL, "Adzuna credentials", "adzuna is enabled but its keys are missing")
    if "usajobs" in enabled:
        if config.USAJOBS_API_KEY and config.USAJOBS_USER_AGENT:
            record(OK, "USAJobs credentials", "set")
        else:
            record(FAIL, "USAJobs credentials", "usajobs is enabled but key or user agent is missing")
    if not enabled:
        record(FAIL, "ENABLED_SOURCES", "empty -- nothing will be fetched")
    else:
        record(OK, "ENABLED_SOURCES", ", ".join(enabled))

    if config.CAREER_LEVEL in config.CAREER_LEVEL_GUIDANCE:
        record(OK, "CAREER_LEVEL", config.CAREER_LEVEL)
    else:
        valid = ", ".join(sorted(config.CAREER_LEVEL_GUIDANCE))
        record(FAIL, "CAREER_LEVEL", f"{config.CAREER_LEVEL!r} is not one of: {valid}")


def check_profile() -> None:
    import config

    if not config.PROFILE_PATH.exists():
        record(FAIL, "profile.txt", "not found -- copy profile.example.txt and make it yours")
        return

    text = config.PROFILE_PATH.read_text(encoding="utf-8").strip()
    if not text:
        record(FAIL, "profile.txt", "empty -- the scorer has nothing to compare against")
        return

    example = config.ROOT / "profile.example.txt"
    if example.exists() and text == example.read_text(encoding="utf-8").strip():
        record(WARN, "profile.txt", "still the example -- every score will be for a fictional candidate")
    elif len(text) < 200:
        record(WARN, "profile.txt", f"only {len(text)} characters, more detail scores better")
    else:
        record(OK, "profile.txt", f"{len(text)} characters")


def check_database() -> None:
    import config
    from db.repository import Repository

    try:
        with Repository() as repo:
            repo.init_schema()
            counts = repo.counts()
        record(OK, "Database", f"{config.DB_PATH.name}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    except (sqlite3.Error, OSError) as exc:
        record(FAIL, "Database", f"cannot open {config.DB_PATH}: {exc}")


def check_live() -> None:
    """One free request per configured source. No paid calls."""
    import config

    if "adzuna" in config.ENABLED_SOURCES and config.ADZUNA_APP_ID:
        from sources import adzuna_client

        found = adzuna_client.fetch(queries=["data analyst"], results_per_query=1)
        if found:
            record(OK, "Adzuna live call", f"returned {len(found)} posting")
        else:
            record(FAIL, "Adzuna live call", "returned nothing -- check the app id and key")

    if "usajobs" in config.ENABLED_SOURCES and config.USAJOBS_API_KEY:
        from sources import usajobs_client

        found = usajobs_client.fetch(queries=["data analyst"], results_per_query=1)
        if found:
            record(OK, "USAJobs live call", f"returned {len(found)} posting")
        else:
            record(FAIL, "USAJobs live call", "returned nothing -- check the key and user agent")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Also make one free request per source to confirm credentials work.",
    )
    args = parser.parse_args()

    check_python()
    check_imports()
    try:
        check_config()
        check_profile()
        check_database()
        if args.live:
            check_live()
    except Exception as exc:  # a broken config should report, not traceback
        record(FAIL, "Configuration", f"{type(exc).__name__}: {exc}")

    print()
    for status, name, detail in _results:
        print(f"[{status}] {name:22} {detail}")

    failures = sum(1 for status, _, _ in _results if status == FAIL)
    warnings = sum(1 for status, _, _ in _results if status == WARN)
    print()
    if failures:
        print(f"{failures} problem(s) to fix before this will run.")
        return 1
    if warnings:
        print(f"Ready, with {warnings} warning(s). Try: python scripts/run_daily.py --dry-run")
        return 0
    print("All good. Try: python scripts/run_daily.py --dry-run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
