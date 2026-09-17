# Job Radar

Checks free public job boards every morning, scores each new posting against
your actual background using Claude, and sends one ranked shortlist to Slack.

The point is to stop scanning job boards. You read eight postings a day that
someone has already judged against your résumé, instead of three hundred that
matched a keyword.

```
*Job Radar, today's top matches:*

[82] *Strong match* — Strategic Market Intelligence Analyst at CACI · Remote · $73k-$149k
https://www.adzuna.com/details/...
_Directly matches the candidate's competitive intelligence pipeline work, though
the security domain is new._

[72] *Bridge* — Entry level Data Analyst at Dhalite Inc. · Chicago · $80k (est.)
https://www.adzuna.com/details/...
_Straightforward SQL reporting the candidate could do today, but it does not
advance the analytics engineering track._
```

## What it costs

Sources are free. The only spend is scoring, on Claude Haiku 4.5.

A scored posting costs about **$0.002**. After the first day, most postings you
fetch have been seen before, so a typical day scores 15–25 new ones — **a few
cents**. `--dry-run` fetches and filters without scoring anything, so you can
see what it would do before spending a cent.

Two guards keep a bad day bounded: `MAX_SCORE_PER_RUN` caps API calls per run,
and descriptions are truncated before they are sent.

## How a run works

1. **Fetch** every enabled source for each of your search queries.
2. **Dedup** by posting id, and by title + company — boards syndicate one
   opening across a dozen state listings, and each arrives with its own id.
3. **Pre-filter**, free and local: target keywords, career level, excluded
   titles, credentials you do not hold, postings older than 14 days.
4. **Score** each survivor with one Claude call, constrained to a JSON schema
   and validated. Every result is stored, so nothing is ever scored twice.
5. **Rank and send** the top few above a quality floor, then record what was
   sent so it never appears again.

Steps 2 and 3 are what make this cheap. On a real run they take ~1,100 fetched
postings down to ~70 worth paying to score.

## Setup

Requires Python 3.11+.

```bash
git clone https://github.com/YOUR-USERNAME/job-radar.git
cd job-radar
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux
pip install -r requirements.txt

cp .env.example .env
cp profile.example.txt profile.txt
```

Then get the keys:

| Variable | Where | Needed for |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | Scoring. Required. Billed separately from a Claude.ai subscription; a few dollars of credit lasts months. |
| `SLACK_WEBHOOK_URL` | Slack app → Incoming Webhooks | Delivery |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | [developer.adzuna.com](https://developer.adzuna.com) | The Adzuna source |
| `USAJOBS_API_KEY` / `USAJOBS_USER_AGENT` | [developer.usajobs.gov](https://developer.usajobs.gov) | US federal roles. The user agent is the email you registered with. |

Then confirm it is wired up correctly:

```bash
python scripts/check_setup.py          # no API calls
python scripts/check_setup.py --live   # one free request per source
python scripts/run_daily.py --dry-run  # fetch and filter, still free
python scripts/run_daily.py --no-slack # score, print the digest locally
python scripts/run_daily.py            # the real thing
```

## Change these three things first

Out of the box this is tuned for an early-career data analyst. If you do not
change these, the scores will be about someone else.

**1. `profile.txt`** — your background in plain prose. Every posting is scored
against it, so detail matters: past roles and what you actually did, tools,
target roles, and anything you would accept as a stopgap. It is read fresh on
every run, so editing it takes effect immediately. Never committed.

**2. `CAREER_LEVEL` in `config.py`** — `"early"`, `"mid"`, or `"senior"`. This
drives which titles are discarded for free *and* how the scorer weighs
seniority. Leaving it at `"early"` as a senior engineer will mark down exactly
the roles you want.

**3. `SEARCH_QUERIES` and `TITLE_KEYWORDS` in `config.py`** — the roles you are
looking for. Fetching is free, so breadth is cheap; the filters bound what
actually gets scored.

Everything else worth tuning is in `config.py` too: `DIGEST_SIZE`,
`MIN_DIGEST_SCORE`, `MATCH_TIER_THRESHOLDS` (the score bands behind the Ideal /
Strong / Bridge labels), `EXCLUDED_TITLE_TERMS`, `BLOCKED_TERMS`, and the cost
guards.

## After changing a filter or a score band

Filters run once, when a posting is first stored, and labels are derived from
the score. Changing either only affects new postings unless you backfill:

```bash
python scripts/reapply_filter.py    # re-run filters over stored postings
python scripts/relabel_scores.py    # recompute labels after moving a band
python scripts/rescore.py --yes     # re-score after editing the profile or prompt
```

The first two are free. `rescore.py` calls the API, so it prints a cost
estimate and refuses to spend without `--yes`.

## Scheduling

**Windows.** One command registers a daily task:

```powershell
.\scripts\install_task.ps1              # daily at 06:00
.\scripts\install_task.ps1 -Time 07:30
```

It generates the task definition from your checkout, so there are no paths to
edit. The generated XML is gitignored because it contains your username.

```powershell
schtasks /query /tn "Job Radar" /fo list /v   # check it, and the next run time
schtasks /run   /tn "Job Radar"               # run it now
schtasks /delete /tn "Job Radar" /f           # remove it
```

The first run is scheduled for *tomorrow* on purpose. Dating it today combines
with catch-up-missed-runs to fire a full run the moment you register it.

**macOS / Linux.** A cron entry does the same job:

```
0 6 * * * cd /path/to/job-radar && ./venv/bin/python scripts/run_daily.py
```

Three settings in the Windows task matter on a laptop and are set for you:
missed runs are caught up rather than skipped, runs are allowed on battery (the
default is to skip them), and a failed run retries three times at 15 minute
intervals to cover waking before the network is back.

Output goes to `logs/job_radar.log`.

## Sources

Only official, free APIs and public JSON feeds. Nothing here scrapes a site
that does not offer an API, and nothing touches LinkedIn or Indeed.

| Source | Key | Notes |
| --- | --- | --- |
| Adzuna | Free | Broad US coverage. Review [their API terms](https://developer.adzuna.com) — attribution may be required. |
| USAJobs | Free | Official US federal listings. |
| Greenhouse | None | Public per-company board feeds. Add slugs to `sources/watched_companies.py`. |
| Lever | None | Same, per company. |

Greenhouse and Lever need you to name companies in advance, so they are off by
default. Enable sources in `config.ENABLED_SOURCES`.

## Layout

```
config.py          every tunable, and secret loading
models.py          Posting, FitScore, ScoredPosting, the score bands
sources/           one client per board, all normalizing to Posting
db/                schema and the SQLite repository
filtering/         the free pre-filter
scoring/           the Claude client and the scoring loop
digest/            ranking and Slack delivery
scripts/           run_daily.py plus the maintenance utilities
tests/             87 tests, no network or API key needed
```

```bash
python -m pytest tests -q
```

## License

MIT. See [LICENSE](LICENSE).
