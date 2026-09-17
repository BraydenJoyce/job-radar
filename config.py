"""Central configuration for Job Radar.

Everything tunable lives here. Secrets come from `.env` (never committed);
everything else is a plain module-level constant you can edit directly.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

load_dotenv(ROOT / ".env")


# --- Paths -----------------------------------------------------------------

DB_PATH = ROOT / "job_radar.db"
SCHEMA_PATH = ROOT / "db" / "schema.sql"
PROFILE_PATH = ROOT / "profile.txt"
LOG_DIR = ROOT / "logs"


# --- Secrets ---------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
USAJOBS_API_KEY = os.getenv("USAJOBS_API_KEY", "")
USAJOBS_USER_AGENT = os.getenv("USAJOBS_USER_AGENT", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


# --- Sources ---------------------------------------------------------------

# Which sources run. "adzuna" and "usajobs" are keyword driven and need only
# their API keys. "greenhouse" and "lever" read one company's board at a time,
# so they do nothing until you list company slugs in
# sources/watched_companies.py.
ENABLED_SOURCES = ["adzuna", "usajobs"]

# What to search for on the keyword-driven sources (Adzuna, USAJobs).
# Keyword driven sources (Adzuna, USAJobs) search each of these separately.
# Fetching is free -- only scoring costs -- and the pre filter plus dedup keep
# the extra volume from turning into extra API calls, so breadth here is cheap.
SEARCH_QUERIES = [
    "data analyst",
    "ai engineer",
    "strategy analyst",
    "competitive intelligence analyst",
    "business intelligence analyst",
    "market intelligence analyst",
    "machine learning engineer",
    "analytics engineer",
    "data engineer",
    "research analyst",
    "entry level data analyst",
]

# Adzuna serves 50 results per page. Page 1 alone is a thin slice of a broad
# nationwide search; each extra page is one more free request.
ADZUNA_PAGES = 2

# Broad by default: empty means nationwide.
SEARCH_LOCATION = ""

# Per query, per source.
RESULTS_PER_QUERY = 50

# --- Adzuna attribution ----------------------------------------------------
#
# Adzuna's API terms require attribution wherever their listings or salary
# estimates are displayed. The digest builds this in; do not strip it out.
# Terms: https://developer.adzuna.com
#
# Which Adzuna country API to query, and the matching consumer domain that
# attribution links must point at ("the relevant local domain").
ADZUNA_COUNTRY = "us"
ADZUNA_SITE_URL = "https://www.adzuna.com"

# The Adzuna logo, shown beside "Jobs by Adzuna" in every digest containing
# their listings. Get the current URL from https://www.adzuna.co.uk/press.html
# -- their press page blocks automated fetches, so it has to be copied by hand.
#
# It MUST be a PNG, JPG or GIF. Slack's image blocks do not support SVG: the
# payload is accepted with a 200 and the logo then renders as a broken image,
# so there is no error to notice. Adzuna's own CDN serves the logo as
# .../images/global/adzuna_logo.svg, which does not work here.
#
# A correctly sized copy ships in assets/adzuna_logo.png (232x59, resized from
# their press kit -- see assets/NOTICE.md). Slack needs a public URL, so point
# this at the raw file once your fork is public:
#
#   https://raw.githubusercontent.com/<you>/job-radar/main/assets/adzuna_logo.png
#
# A raw URL on a private repo returns 404 to Slack, which renders as a broken
# image. Left empty, the digest carries the text attribution and links and logs
# a warning instead. That is the better failure: text-only attribution reads
# fine, a broken image does not.
ADZUNA_LOGO_URL = "https://raw.githubusercontent.com/BraydenJoyce/job-radar/main/assets/adzuna_logo.png"

# Adzuna calls their salary estimates "Jobsworth". Every estimate shown must be
# labelled and linked back to this page.
ADZUNA_JOBSWORTH_URL = "https://www.adzuna.com/jobs/salary-predictor.html"

HTTP_TIMEOUT_SECONDS = 30.0


# --- Pre filter ------------------------------------------------------------

# A posting is only scored if its title loosely contains one of these.
TITLE_KEYWORDS = [
    "data",
    "analyst",
    "analytics",
    "ai",
    "machine learning",
    "strategy",
    "intelligence",
    "research",
]

# Hard blockers: credentials the candidate does not hold. Matched against the
# title and description.
BLOCKED_TERMS = [
    "security clearance",
    "active clearance",
    "ts/sci",
    "top secret",
    "polygraph",
    "secret clearance",
    "nursing license",
    "registered nurse",
    "rn license",
    "lpn",
    "cdl license",
    "class a cdl",
    "medical license",
    "pharmacist license",
    "law license",
    "bar admission",
]

# --- Career level ----------------------------------------------------------
#
# CHANGE THIS FIRST. It drives both which titles are discarded for free and how
# the scorer weighs seniority, and the wrong value quietly ruins every score:
# an "early" setting marks down the exact roles a senior candidate should see.
#
#   "early"  -- student, new graduate, or one or two years in
#   "mid"    -- a few years in, individual contributor
#   "senior" -- senior, lead, or staff level and looking at the same
#
CAREER_LEVEL = "early"

# Title terms discarded before scoring, per career level. A level you will not
# realistically be hired into is noise worth dropping for free; every senior
# titled posting scored under the "early" setting topped out at 52, well under
# the digest floor, so paying to score them only ever bought rejections.
#
# "manager" is deliberately absent everywhere: the title covers too wide a
# range of seniority to reject on sight. Add it if it turns out to be noise.
SENIORITY_EXCLUSIONS = {
    "early": [
        "director",
        "vp",
        "vice president",
        "principal",
        "staff",
        "head of",
        "senior",
        "sr",
        "lead",
        "chief",
        "executive",
        # Federal listings use "supervisory" where private ones say "manager".
        "supervisory",
        "supervisor",
    ],
    "mid": [
        "director",
        "vp",
        "vice president",
        "head of",
        "chief",
        "executive",
        "supervisory",
        "supervisor",
    ],
    # A senior candidate should see senior titles, so only the very top is cut.
    "senior": [
        "chief",
        "vp",
        "vice president",
    ],
}

# Dropped whatever the career level. Internships sit at the opposite end of the
# scale from the seniority terms, but they are excluded for the same reason:
# they are not roles worth spending attention or API budget on.
ALWAYS_EXCLUDED_TITLE_TERMS = [
    "intern",
    "interns",
    "internship",
    "internships",
    "co-op",
    "coop",
]

EXCLUDED_TITLE_TERMS = (
    SENIORITY_EXCLUSIONS[CAREER_LEVEL] + ALWAYS_EXCLUDED_TITLE_TERMS
)

MAX_POSTING_AGE_DAYS = 14


# --- Scoring ---------------------------------------------------------------

# Haiku 4.5: $1 / MTok input, $5 / MTok output. With descriptions capped at
# DESCRIPTION_CHAR_LIMIT (~1.5K tokens) plus a ~500 token profile, a scored
# posting costs roughly $0.002, so a 30 posting day lands around 6 cents.
SCORING_MODEL = "claude-haiku-4-5"
SCORING_MAX_TOKENS = 400

# Descriptions are truncated before they reach the API. This is the single
# biggest lever on daily cost -- raw postings are frequently 20K+ characters.
DESCRIPTION_CHAR_LIMIT = 6000

# Hard ceiling on API calls per run, so a bad fetch day cannot run up a bill.
# Steady state is 15-25 new postings a day, well under this; the cap only bites
# on a backlog, which is what a fresh install or a widened set of queries
# creates. Raise it temporarily to drain one, then put it back.
MAX_SCORE_PER_RUN = 60

# One retry on an unparseable response, then the posting is skipped.
SCORING_RETRIES = 1

# How the scorer weighs seniority, chosen by CAREER_LEVEL. This text goes into
# the prompt verbatim. Without it the model reads a job title at face value and
# scores a Director role as a strong match for a new graduate, purely because
# the subject matter lines up.
CAREER_LEVEL_GUIDANCE = {
    "early": """The candidate is early career: a recent graduate with internship or project experience rather than years on the job. Weigh seniority as heavily as subject matter.
- Director, VP, Head of, Principal, or Staff titles, or 5+ years of required experience: below 40, however well the subject matter matches.
- Senior or Lead titles, or 3 to 5 years required: below 70.
- Entry level, associate, or 0 to 2 years: no seniority penalty.
- US federal postings: GS-12 and above expect years of professional experience the candidate does not have, so treat them as senior. GS-5 through GS-9 is the entry range. When a posting spans a range, judge it on the lowest grade offered.""",
    "mid": """The candidate is mid career: a few years of professional experience as an individual contributor. Weigh seniority alongside subject matter.
- Director, VP, or Head of titles, or 10+ years of required experience: below 40.
- Entry level or internship roles: below 50, since they are a step backwards.
- Senior or Lead titles, or 3 to 7 years required: no penalty, these are the target.
- US federal postings: GS-11 through GS-13 is the target range. GS-7 and below is a step backwards; GS-14 and above expects management experience.""",
    "senior": """The candidate is senior: many years of professional experience, and is looking at senior, lead, and staff level roles. Weigh seniority alongside subject matter.
- Entry level, associate, or junior roles, or 0 to 2 years required: below 40, they are a step backwards.
- Mid level roles with no scope for ownership: below 60.
- Senior, Lead, Staff, or Principal titles: no penalty, these are the target.
- US federal postings: GS-13 and above is the target range. GS-11 and below is a step backwards.""",
}

# Scoring is classification, not writing. The SDK default of 1.0 makes the
# same posting score 10 to 15 points apart across runs, which is enough to
# flip a posting sitting near a band edge between two labels.
SCORING_TEMPERATURE = 0.0

# Score bands. The label is derived from the score rather than left to the
# model, so "ideal" cannot drift back onto a merely decent match. These
# numbers are the goalposts -- move them here and every label follows.
MATCH_TIER_THRESHOLDS = {
    "ideal": 85,   # on the target trajectory, worth applying to today
    "strong": 75,  # a real fit with a clear gap
    "bridge": 60,  # plausible near term income, does not advance the target
}
# Anything below the lowest threshold is "weak" and never reaches the digest.


# --- Digest ----------------------------------------------------------------

DIGEST_SIZE = 8

# Postings below this never make the digest, even if the day is quiet.
# Kept in step with the "bridge" floor below: anything weaker is not worth
# a slot in a list you are supposed to actually read.
MIN_DIGEST_SCORE = 60

# A scored posting that never made the cut stays a candidate for this many
# days, then ages out rather than competing against fresh postings forever.
DIGEST_CANDIDATE_DAYS = 3


# --- Logging ---------------------------------------------------------------

def setup_logging(level: int = logging.INFO) -> None:
    """Log to console and to logs/job_radar.log."""
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_DIR / "job_radar.log", encoding="utf-8"),
        ],
    )
    # httpx logs every request at INFO, which drowns out the pipeline.
    logging.getLogger("httpx").setLevel(logging.WARNING)
