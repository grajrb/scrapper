"# scrappeer — Local-First Job-Search Aggregation Engine

A personal, modular job-search aggregator written in Python. It **discovers,
normalizes, deduplicates, filters, scores, ranks and exports** job postings
from company career pages, ATS platforms and job boards — locally, at ~₹0 cost.

> **It NEVER applies to jobs.** No CAPTCHA bypass, no authentication bypass,
> no anti-bot evasion, no automated submissions. Sources that block
> automation are marked `MANUAL_REVIEW` and reviewed manually.

## ⚠ Current status: PHASE 1 (foundation)

| Area | Status |
|---|---|
| Project structure, config, models, SQLite, logging | ✅ done |
| Adapter interface + plugin registry | ✅ done |
| Filtering, scoring (0–100), ranking, deduplication | ✅ done |
| CSV + Excel (7 sheets) exports, terminal reports, CLI | ✅ done |
| Test suite (97 tests, fully offline) | ✅ done |
| Career-page / ATS discovery (`discover`) | ⏳ Phase 2 — *not implemented* |
| ATS adapters (Greenhouse, Lever, Workday, …) | ⏳ Phase 3 — *no adapter yet* |
| Job-board adapters (Indeed, Hirist, Naukri, LinkedIn, …) | ⏳ Phase 4 — *no adapter yet* |
| Fuzzy target-company matching | ⏳ Phase 5 |
| Scheduler command | ⏳ Phase 7 (manual/cron scheduling works today) |

**Phase 1 performs no live web scraping.** The only source that returns jobs
today is the `fixture` adapter, serving **clearly-labeled fabricated test
data** (`data/raw/fixture_jobs.json`, flagged `is_fixture=true` everywhere) so
the pipeline can be exercised offline. Enabled sources without an adapter are
honestly reported as `NOT_AVAILABLE` — nothing is faked.

---

## 1. What the project does

1. Keeps your target-company list (`config/companies.csv`, ready for ~420 rows).
2. (Phase 2+) Discovers each company's careers page and ATS provider.
3. Runs configured source adapters to collect publicly available postings.
4. Normalizes every source into one common `Job` format.
5. Deduplicates across sources (career page > ATS > job board priority),
   keeping every source reference.
6. Filters jobs by roles/locations/experience/skills/target companies.
7. Scores each job 0–100 with human-readable **reasons** and **warnings**.
8. Ranks by score → company priority → recency.
9. Tracks new/seen/inactive jobs across runs (rows are never deleted).
10. Exports CSV + a 7-sheet Excel workbook and prints a terminal report.

## 2. Architecture

```
config (companies.csv, search_config.yaml, sources.yaml)
        │
        ▼
┌────────────┐   RawJob    ┌────────────┐  Job   ┌──────────────┐
│  Adapters   │ ─────────► │ Normalizer │ ─────► │ Deduplicator │
│  (plugins)  │            └────────────┘        └──────┬───────┘
└────────────┘                                          ▼
  company_careers, generic, fixture,                SQLite (data/jobs.db),
  greenhouse, lever, workday, ashby, ...            job_sources, companies,
  indeed, naukri, hirist, linkedin, ...             sources, scrape_runs,
        │                                           scrape_errors, ats_discovery,
        ▼                                           notifications
   Filter → Scoring (0–100) → Ranking → Export (CSV/Excel) + Report + Notifications
```

Key rules:

- **The core never contains source-specific logic.** All website knowledge
  lives in `src/adapters/<source>.py`.
- Adapters implement `discover()`, `search()`, `fetch_jobs()`, `normalize()`,
  `health_check()` and return the same `Job` object.
- Every adapter talks to the web through the shared polite `HttpClient`
  (delay, timeout, retries with backoff, cache; **403/429/CAPTCHA are never
  retried** — they become `MANUAL_REVIEW`).

Project layout:

```
scrappeer/
├── config/            companies.csv, search_config.yaml, sources.yaml
├── src/
│   ├── main.py        CLI (discover/scrape/new/export/status/errors/test)
│   ├── config.py  models.py  database.py  logging_config.py
│   ├── normalization.py  deduplication.py  filtering.py
│   ├── scoring.py     ranking.py  exporters.py  reporting.py
│   ├── adapters/      base.py, http.py, generic.py, fixture.py, <source>.py…
│   └── services/      job_service.py, notification_service.py
├── data/              jobs.db, raw/ (logs, fixture), exports/
├── tests/             97 offline tests (mocked adapters/HTTP)
└── README.md  requirements.txt  .env.example  pytest.ini
```

Modules planned for later phases (`discovery.py`, `scheduler.py`,
`services/company_discovery.py`, `services/ats_detection.py`) are **not
created until implemented** — no empty placeholders pretending to work.

---

## 3. Installation

Requires Python 3.11+ (tested on 3.13, Windows).

```bash
git clone https://github.com/grajrb/scrapper.git
cd scrapper
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m src.main test         # offline self-check -> "SELF CHECK PASSED"
python -m pytest                # run the test suite (97 tests, no network)
```

Dependencies (all free): `requests`, `PyYAML`, `openpyxl`, `python-dotenv`,
`pytest`.

Copy `.env.example` to `.env` only to override defaults
(`JOB_SEARCH_LOG_LEVEL`, `JOB_SEARCH_DB_PATH`). The real `.env` is
git-ignored. **No credentials are required or stored.**

---

## 4. Configuration

| File | Purpose |
|---|---|
| `config/companies.csv` | Your target companies (see §5) |
| `config/search_config.yaml` | Roles, locations, experience, skills, scoring weights, filter options |
| `config/sources.yaml` | Enable/disable each source + rate limits (`request_delay`, `timeout`, `max_retries`, `backoff_factor`, `cache_ttl`) |
| `.env` (optional) | Local overrides; never committed |

Important `search_config.yaml` keys:

```yaml
roles: [software engineer, backend engineer, software developer, sde]
locations: [Bangalore, Bengaluru, Hyderabad, Pune, Mumbai, Remote]
remote_preference: any        # any | prefer | require | onsite
experience_min: 2
experience_max: 5
skills: [Python, SQL, AWS, Django, FastAPI]
preferred_skills: [Docker, Kubernetes, Redis]
excluded_keywords: [internship, director, vice president]
minimum_match_score: 50       # below this: stored, but not counted as relevant
high_match_score: 75          # report + "High Match" sheet threshold
scoring:
  weights: {title: 30, skills: 30, experience: 20, location: 15, employment_type: 5}
filtering:
  require_target_company: true
```

In `sources.yaml`, per-source overrides are supported:

```yaml
sources:
  workday:
    enabled: true
    request_delay: 3.0    # be extra polite to heavy platforms
    timeout: 30
```

## 5. Adding companies

Edit `config/companies.csv`:

```csv
company_name,company_domain,careers_url,priority,enabled
Company A,https://companya.com,,A,true
Company B,https://companyb.com,,B,true
```

- `careers_url` may be empty — discovery arrives in Phase 2 (paste it now so
  it is used as soon as Phase 2 lands).
- `priority` = `A`/`B`/`C`; ties in match score are broken by priority.
- `enabled=false` skips the company without deleting it.
- 8 fictional `.example` companies ship as Phase-1 test data — replace them
  with your real list (~420 rows supported; the companies table is indexed).

## 6. Adding a new source

1. Create `src/adapters/<source>.py`:

```python
from ..models import (AdapterResult, Company, ResultStatus, SearchMode,
                      SearchQuery, SourceType)
from .base import SourceAdapter, register

@register
class GreenhouseAdapter(SourceAdapter):
    source_key = "greenhouse"            # must match sources.yaml
    source_type = SourceType.ATS
    search_mode = SearchMode.BOARD       # or SearchMode.COMPANY

    def discover(self, company): ...     # company mode: careers page -> jobs
    def search(self, query): ...         # board mode: query -> RawJob list
    def fetch_jobs(self, target): ...    # entry point used by the pipeline
    def health_check(self): ...          # cheap probe -> HealthStatus

    # Map source-specific fields into the CANONICAL RAW PAYLOAD schema
    # documented at the top of adapters/base.py. Never invent values.
```

2. Add the key to `config/sources.yaml`.
3. Write mocked tests under `tests/adapters/` — never live sites.
4. `python -m src.main test` should now show the adapter healthy.

No core file (database, filtering, scoring, exports, other adapters) needs
any change — that is the point of the registry (`adapters/__init__.py`
auto-imports every module in the package).

---

## 7. Running a scrape

```bash
python -m src.main scrape                      # everything enabled
python -m src.main scrape --source greenhouse   # one source (repeatable)
python -m src.main scrape --company "Acme"      # companies matching text
python -m src.main scrape --limit 10            # first N companies only
python -m src.main scrape --mode company        # company-first mode only
python -m src.main scrape --mode board          # job-board mode only
python -m src.main scrape --source fixture      # offline demo/test run
```

Other commands:

```bash
python -m src.main new        # NEW SINCE LAST RUN / last 24h / last 7d
python -m src.main status     # DB stats + per-source status table
python -m src.main errors     # recent scrape errors / MANUAL_REVIEW items
python -m src.main test       # offline self-check (config, adapters, DB, smoke)
python -m src.main discover   # Phase 2 — prints "not implemented" honestly
```

Sample end-of-run report:

```
======================================================
SCRAPE COMPLETE
======================================================
Companies:              7
Processed:              7
Failed:                 0
Sources selected:       1
Jobs found:             14
New:                    12
Duplicates:             2
Filtered out:           6
High match:             5
Manual review:          0
Errors:                 0
Duration:               0.06s
======================================================
TOP MATCHES
   88/100  Acme Cloud - Senior Backend Engineer (Bangalore, India [FIXTURE])
   ...
```

One failing company/source **never** stops the run: it is logged to
`scrape_errors`, the source is marked `FAILED`/`MANUAL_REVIEW`, and the run
continues. 403/429/CAPTCHA are never retried.

## 8. Exporting jobs

```bash
python -m src.main export                 # CSV + Excel into data/exports/
python -m src.main export --format csv
python -m src.main export --format xlsx --out D:\some\folder
```

- **CSV** — one file with all active jobs (utf-8-sig, opens cleanly in Excel).
- **Excel** — 7 sheets: `New Jobs`, `High Match`, `All Active Jobs`,
  `Target Companies`, `Sources`, `Scrape Errors`, `ATS Discovery`.
- Columns: Company, Priority, Job Title, Location, Remote, Experience,
  Match Score, Match Reasons, Posted Date, First Seen, Source, ATS,
  Canonical URL, Application URL, Status.
- **Application URL** always picks the best available link:
  official career page → official ATS → job board. It is only a link —
  **the system never applies for you.**
- Fixture rows are labeled `[FIXTURE]` in the Status column.

## 9. Filtering jobs

Filters come from `config/search_config.yaml` (see §4) and run **before**
scoring, in this order:

1. target company required? (exact name/domain match in Phase 1)
2. excluded keywords in title
3. role match (full phrase → partial token overlap ≥ 50%)
4. location (with aliases: Bengaluru↔Bangalore, Mumbai↔Bombay) + remote policy
5. experience range overlap (missing experience → kept, never guessed)
6. employment type
7. required skills (`skill_match_mode: any` with `min_skill_matches`,
   or `all`)

Rejected jobs are still stored (with no score) so you can audit why.
`minimum_match_score` afterwards separates "relevant" from "below threshold".
Scoring weights are editable; missing data yields **warnings**, never
invented values (policy: `neutral` | `zero` | `full`).

## 10. Scheduling

No cloud, no paid services. From the project root:

**Windows Task Scheduler**

```bat
schtasks /create /tn "Scrappeer Daily" /sc daily /st 08:00 ^
  /tr "cmd /c cd /d D:\Projects\scrappeer && python -m src.main scrape && python -m src.main export"
```

(or Task Scheduler GUI → Action → Create Task → Program: `python`,
Arguments: `-m src.main scrape`, Start in: `D:\Projects\scrappeer`)

**macOS / Linux cron** (every day 08:00):

```cron
0 8 * * * cd /path/to/scrappeer && /path/to/.venv/bin/python -m src.main scrape >> data/raw/cron.log 2>&1
```

Every 12 hours: `0 8,20 * * * ...`

A built-in `scheduler.py` command (run inside a terminal) is planned for
Phase 7; cron/Task Scheduler already give you full local scheduling today.

---

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Configuration error: Config file not found` | Run commands from the project root (where `config/` lives). |
| `sources.<x>` shows `NOT_AVAILABLE` | No adapter exists for that source yet (Phase 3/4). Nothing is faked — this is expected today. |
| `MANUAL_REVIEW` in `errors` | The source (or company page) requires manual handling. Follow the logged `recommended_action`; do not bypass it. |
| `SELF CHECK FAILED` | Run `python -m src.main test`; it names the failing part (config, adapter health, smoke pipeline). |
| Excel won't open the `.xlsx` | Re-run `python -m src.main export`; files are written with openpyxl (standard OOXML). |
| Stale jobs showing | Jobs not seen for `inactive_after_days` (default 14) become `INACTIVE`; rows are never deleted. |
| SQLite `database is locked` | Only run one scrape at a time (WAL mode is enabled; a second concurrent writer can still conflict). |
| Logs | `data/raw/logs/jobsearch.log` (rotating, 2 MB × 3) + console output. `JOB_SEARCH_LOG_LEVEL=DEBUG` for verbose. |
| Want a clean slate | Stop all runs, delete `data/jobs.db` (and `data/jobs.db-wal`/`-shm`), re-run `scrape`. |

## 12. Legal / ethical limitations

This is a **personal research tool**. By design it:

- does **not** bypass CAPTCHAs, authentication, paywalls, IP/rate limits or
  any access-control or anti-bot mechanism;
- does **not** use credentials, cookies, tokens or fake accounts;
- does **not** scrape private/user-only data or personal information;
- does **not** submit applications automatically — ever;
- **does** send modest, rate-limited requests with an honest User-Agent,
  honours timeouts/retries/backoff and reuses cached pages;
- **stops** when a source blocks automation and returns `MANUAL_REVIEW`
  with source, URL, reason and recommended manual workflow.

You are responsible for complying with each site's Terms of Service,
`robots.txt`, and applicable law (including the IT Act and copyright rules
in India, or equivalent rules in your jurisdiction). Some sources listed in
the brief (LinkedIn, Naukri, Indeed, Hirist…) actively restrict automation;
if they do, Phase 4 will keep them at `MANUAL_REVIEW` instead of evading the
restriction. Prefer official APIs and public feeds wherever they exist.

## 13. How to test adapters

**Unit tests (offline, required):**

```bash
python -m pytest                       # all 97 tests
python -m pytest tests/adapters        # adapter + HTTP-client tests only
python -m pytest tests/test_scoring.py -q
```

- Mock responses with fake sessions (see `FakeSession` in
  `tests/adapters/test_base_and_http.py`) — tests must never touch the net.
- Verify: interface completeness, raw-payload → `Job` mapping, missing fields
  stay `None`, `MANUAL_REVIEW` behavior on 403/429/CAPTCHA, retry/backoff on
  5xx, rate-limit delay, caching.

**Live checks (manual, Phase 3+ only):** enable one source, run
`python -m src.main scrape --source <key> --limit 3`, then inspect
`python -m src.main status`, `errors` and the stored rows. Document the
result honestly — an adapter is only "supported" after it has been tested
against real data.

**Offline self-check any time:**

```bash
python -m src.main test
```

---

## Development roadmap

- **Phase 1 (done)** — structure, config, models, SQLite, logging, adapter
  interface, filtering, scoring, dedup, CSV/Excel export, tests.
- **Phase 2** — company-career discovery + ATS detection, tested on 5–10
  real companies, then stop and report.
- **Phase 3** — ATS adapters one at a time (Greenhouse → Lever → Workday →
  Ashby → SmartRecruiters → iCIMS → Taleo → Jobvite → BambooHR → Recruitee
  → Teamtailor → SuccessFactors), each tested before claiming support.
- **Phase 4** — job-board adapters only where automation is permitted;
  everything else stays `MANUAL_REVIEW`.
- **Phase 5** — cross-source canonical URLs, fuzzy target-company matching.
- **Phase 6** — scale 10 → 50 → 100 → 420 companies; measure time, failure
  rate, duplicate rate, reliability.
- **Phase 7** — scheduling command, richer reports, optional free
  notifications (email/Telegram/Discord/Slack via webhook).

## Known limitations (Phase 1)

- **No live scraping yet** — the pipeline is real, but job data comes only
  from the labeled fixture file until Phases 3–4 land.
- No ATS detection/career discovery yet (`discover` says so explicitly).
- Target-company matching is exact (normalized name/domain) only — fuzzy
  matching is Phase 5.
- `industries` config is accepted but unused (jobs carry no industry field).
- Concurrency is intentionally not used yet; Phase 6 adds only rate-limit-safe
  parallelism.
- Fixture `jobs_found` counters are cumulative across runs.

" 
