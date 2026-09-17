# Job Radar

A personal, low cost tool that checks free public job boards every day, scores each new posting against your actual background using AI, and sends a ranked shortlist to Slack each morning. The goal is to stop manually scanning job boards and only spend attention on postings that are genuinely worth applying to.

This document is the full build spec, meant to be handed to Claude Code as the source of truth for implementation.

## Table of contents

1. Vision and goals
2. Constraints
3. High level architecture
4. Environment setup
5. Data sources
6. Database schema
7. Your profile (what the scorer compares jobs against)
8. Pre filtering (cheap filter before spending on AI scoring)
9. AI fit scoring
10. Ranking and the daily digest
11. Slack setup
12. Scheduler
13. Folder and file structure
14. Phased roadmap
15. Future ideas

---

## 1. Vision and goals

- Automatically discover new job postings across free public sources every day, without manually checking multiple sites.
- Score every new posting against your real background (not just keyword matching) so the shortlist reflects actual fit, not just title matches.
- Distinguish between two different kinds of good matches: a "bridge opportunity" (something you could get quickly and that pays the bills while you keep searching) and an "ideal fit" (a role that matches your target trajectory in data, AI, and strategy).
- Deliver one clean Slack message a day with the top matches, instead of a firehose of every posting found.
- Keep ongoing cost to a few cents a day. Data sources are free. The only real cost is the AI scoring step, which should use a cheap model.

## 2. Constraints

- Job sources must be free and must not violate a site's terms of service. No scraping LinkedIn or Indeed directly. Stick to official free APIs and public job board feeds.
- AI scoring runs on the Claude API (Haiku tier), since it is cheap enough for daily use at this volume and does a much better job than local models at nuanced fit reasoning against a resume. This is the one part of the system allowed to cost money, and it should stay in the range of a few cents per day.
- Delivery is Slack only for now, via an incoming webhook. No email, no dashboard, at least in phase 1.
- Runs on the same personal Windows laptop with 16 GB of RAM used for other projects. No dedicated server required, since this only needs to run once a day for a few minutes.

## 3. High level architecture

The system runs once a day, in this order:

1. Fetch: pull new postings from each free job source for a set of target search queries.
2. Dedup: compare against previously seen postings, keep only new ones.
3. Pre filter: cheaply discard postings that are obviously irrelevant, before spending any AI budget on them.
4. Score: send each surviving posting to Claude Haiku along with your profile, get back a fit score, a short reason, and a bridge versus ideal flag.
5. Rank and digest: sort by fit score, take the top results, and send one Slack message.

## 4. Environment setup

1. Python 3.11 or newer, same virtual environment approach as other projects:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install httpx pandas pydantic apscheduler python-dotenv anthropic
   ```
2. Get a free Anthropic API key from the Claude Console (console.anthropic.com) for the scoring step. Store it in a `.env` file, never committed to source control.
3. Get a free Adzuna API key (app ID and app key) from developer.adzuna.com.
4. No key is required for USAJobs' public search endpoint, Greenhouse job board feeds, or Lever job board feeds.

## 5. Data sources

### 5.1 Adzuna

Free API key required, generous free tier for personal use.

- Endpoint: `https://api.adzuna.com/v1/api/jobs/us/search/{page}`
- Query parameters include `what` (search term, for example "data analyst") and `where` (location, can be left broad for a nationwide search).
- Covers a wide range of US postings across industries, which fits a broad, nationwide search.

### 5.2 USAJobs

Free, official US federal government job board API.

- Endpoint: `https://data.usajobs.gov/api/search`
- Requires a free registration for an API key and a user agent header, but no cost.
- Useful if federal or government adjacent roles (a category worth including given your strategy and competitive intelligence targets) come up.

### 5.3 Greenhouse and Lever public job boards

Many mid size and large companies post their openings through Greenhouse or Lever, both of which expose a free, public, unauthenticated JSON feed per company:

- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs`
- Lever: `https://api.lever.co/v0/postings/{company_slug}?mode=json`

This requires knowing a company's slug in advance, so this source works best as a maintained list of companies you specifically want to watch (start with a short list of 10 to 20 companies you have already applied to or are interested in, and expand it over time).

### 5.4 Remotive (optional, phase 2)

Free, no key required, focused on remote roles. Useful once you decide to widen the net beyond in person US roles.

- Endpoint: `https://remotive.com/api/remote-jobs`

## 6. Database schema

SQLite, single file, `job_radar.db`.

```sql
CREATE TABLE postings (
    posting_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    url TEXT NOT NULL,
    description TEXT NOT NULL,
    posted_at TEXT,
    first_seen_at TEXT NOT NULL,
    passed_pre_filter INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE scores (
    posting_id TEXT PRIMARY KEY REFERENCES postings(posting_id),
    fit_score INTEGER NOT NULL,
    reasoning TEXT NOT NULL,
    match_type TEXT NOT NULL,
    scored_at TEXT NOT NULL
);

CREATE TABLE digests (
    digest_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at TEXT NOT NULL,
    posting_ids TEXT NOT NULL
);
```

`match_type` is either `"bridge"` or `"ideal"`, set by the scoring step. `posting_ids` in the `digests` table stores a comma separated list of what was sent, so a posting never appears twice in your Slack feed even if it stays in the database.

## 7. Your profile

The scorer needs a written summary of your actual background to compare postings against. Store this as a plain text file, `profile.txt`, in the project root, so it can be edited any time without touching code.

Example (this is `profile.example.txt`, shipped with the repo):

```
Jordan Rivera. B.S. Information Systems, State University, 2025.

Target roles: data analyst, business intelligence analyst, analytics engineer. Interested in roles where reporting work sits close to the decisions it informs.

Experience:
- Data Analytics Intern at Northgate Logistics: built a Python pipeline that consolidated carrier invoices from four systems into a single reconciliation report, cutting a two day manual process to under an hour. Presented monthly cost variance findings to operations leads.
- Student Analyst at the university's institutional research office: maintained enrollment dashboards in Tableau, wrote SQL extracts against the student records database.
- Barista at a regional coffee chain through school.

Technical skills: SQL (PostgreSQL, SQL Server), Python for data work (pandas, requests, openpyxl), Tableau, Excel including Power Query, basic dbt, git. Comfortable reading an API doc and writing the client.

Personal projects: a scraper and dashboard tracking regional rental prices, built with Python and Streamlit; a small ETL project loading public transit data into DuckDB for schedule reliability analysis.

Open to bridge roles that provide near term income while continuing to target analytics work with more ownership.
```

Update this file any time your target roles or experience summary changes. The scoring step always reads the current version.

## 8. Pre filtering

Before spending any AI budget, apply cheap, deterministic filters to cut obvious non matches:

- Discard postings whose title contains none of your target keywords (data, analyst, AI, machine learning, strategy, intelligence, research) even loosely.
- Discard postings that explicitly require a security clearance you do not hold, or a professional license unrelated to your background (for example, a nursing license).
- Discard postings older than 14 days, since freshness matters for a discovery tool like this.

Mark postings that fail this filter with `passed_pre_filter = 0` and skip them in the scoring step, but keep them in the database so they are never re fetched or re evaluated later.

## 9. AI fit scoring

For every posting that passes the pre filter and has not already been scored, send a single Claude Haiku call:

```
You are helping evaluate job postings against a candidate's background for personal job search use.

Candidate profile:
{profile_txt}

Job posting:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Score this posting's fit for the candidate from 0 to 100. Then classify it as either "bridge" (something the candidate could likely get quickly, providing near term income, even if it is not their ideal long term fit) or "ideal" (a strong match to their target trajectory in data, AI, or strategy roles). Respond only with JSON:
{{"fit_score": <integer 0-100>, "match_type": "bridge" or "ideal", "reasoning": "<one sentence>"}}
```

Validate the response with pydantic. If parsing fails, retry once, then skip that posting and log the failure. Store every result in the `scores` table, keyed by `posting_id`, regardless of score, since low scores are still useful history to avoid re scoring the same posting later.

## 10. Ranking and the daily digest

Each day, after scoring finishes:

```
candidates = get_scores_from_today()
top_matches = sorted(candidates, key=lambda c: c.fit_score, descending=True)[:8]
send_slack_digest(top_matches)
mark_as_sent(top_matches)
```

Cap the digest at around 8 postings a day. A shorter, higher quality list is more likely to actually get read and acted on than a long one.

## 11. Slack setup

1. Create a Slack workspace (or use an existing one) and add an "Incoming Webhook" app to get a webhook URL.
2. Store the URL in `.env` as `SLACK_WEBHOOK_URL`.
3. Format the digest as a single message with one line per posting:

```python
import httpx

def send_slack_digest(matches):
    if not matches:
        return
    lines = ["*Job Radar, today's top matches:*"]
    for m in matches:
        tag = "Bridge" if m.match_type == "bridge" else "Ideal fit"
        lines.append(f"[{m.fit_score}] *{tag}* — {m.title} at {m.company}\n{m.url}\n_{m.reasoning}_")
    httpx.post(SLACK_WEBHOOK_URL, json={"text": "\n\n".join(lines)})
```

## 12. Scheduler

Run the full pipeline once a day, ideally early morning so the digest is waiting when you start your day. Windows Task Scheduler running a single Python entry point script is the simplest option, and does not require the laptop to be running continuously, only at the scheduled time each day. The `apscheduler` package is an alternative if you would rather keep a long running Python process instead of a system level scheduled task.

## 13. Folder and file structure

```
job-radar/
    job_radar.db
    profile.txt
    .env
    requirements.txt
    config.py
    sources/
        adzuna_client.py
        usajobs_client.py
        greenhouse_client.py
        lever_client.py
        watched_companies.py
    db/
        schema.sql
        repository.py
    filtering/
        pre_filter.py
    scoring/
        scorer.py
        claude_client.py
    digest/
        slack.py
        ranker.py
    scripts/
        run_daily.py
    tests/
        test_pre_filter.py
        test_scorer.py
```

## 14. Phased roadmap

**Phase 0: Environment**
Set up the Python environment, get the Adzuna and Claude API keys, create the SQLite database, write `profile.txt`.

**Phase 1: Minimum viable pipeline**
Wire up Adzuna only, to keep the first version simple. Fetch, dedup, pre filter, score, and send one real Slack digest. Goal: confirm the whole pipeline runs end to end and the fit scores actually feel accurate when you read them.

**Phase 2: Add more sources**
Add USAJobs and a starter list of 10 to 20 watched companies on Greenhouse and Lever. Goal: widen coverage without widening noise, since the pre filter should keep the extra volume manageable.

**Phase 3: Tune the scorer**
After a week or two of real digests, review which postings actually turned out to be worth applying to versus which the scorer over or under rated. Adjust the scoring prompt and `profile.txt` based on what you learn. Goal: the fit scores start to feel trustworthy enough that you stop double checking every posting yourself.

**Phase 4: Automate fully**
Set up the Windows Task Scheduler entry so the whole thing runs on its own every morning with no manual step. Goal: the tool disappears into the background and just shows up in Slack.

**Phase 5 and beyond (open ended)**
Ideas to explore once the core system is stable are listed in section 15.

## 15. Future ideas

- Track which digest postings you actually applied to (a simple Slack reaction or a quick command could log this) so you can eventually measure how well the fit score predicts what you act on.
- Add Remotive and widen to remote roles once the in person US pipeline feels solid.
- Feed application outcomes (interview invitations, rejections) back into the profile or scoring prompt over time, so the system's sense of what counts as a good fit sharpens as your search progresses.
- Add a lightweight weekly summary alongside the daily digest, showing total postings seen, average fit score, and how many bridge versus ideal matches came through that week.
- Extend the watched company list into its own small maintenance routine, so new companies of interest are easy to add without touching code.
