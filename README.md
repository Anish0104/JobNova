# LinkedIn Job Source Agent

Resolves a LinkedIn job posting to the company's own careers or ATS job-listings page
(Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Jobvite, or a self-hosted
careers page). FastAPI backend + a small vanilla-JS frontend, deployable as a single
Docker image.

## Setup

```bash
python3.11 -m venv .venv   # any Python 3.11+ works, e.g. python3.12
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Copy `.env.example` to `.env` and set your free [Groq](https://console.groq.com) API key
(only needed for the LLM tiebreaker step — the pipeline still runs without it, falling
back to its own keyword-scoring heuristic):

```bash
cp .env.example .env
# then edit .env and set GROQ_API_KEY=...
```

`.env` is gitignored — never commit it.

## Usage

### As a library

```python
from job_agent.pipeline import resolve_job_listing_url

result = resolve_job_listing_url("https://www.linkedin.com/jobs/view/4427787182/")
print(result)
# {
#   "linkedin_job_url": ...,
#   "company_name": "Harvey",
#   "company_linkedin_url": "https://www.linkedin.com/company/harvey-ai",
#   "company_website": "https://www.harvey.ai",
#   "careers_page_url": "https://www.harvey.ai/en-US/careers",
#   "jobs_list_url": "https://www.harvey.ai/careers",
#   "ats_platform": null,
#   "status": "success",
#   "reason": "Resolved to the company's careers page",
#   "errors": [],
#   "stages": [...],
#   "elapsed_ms": 13003,
# }
```

### Web app

```bash
uvicorn app:app --reload
```

Open `http://localhost:8000`. Paste a LinkedIn job URL and click **Resolve** to watch
each stage (LinkedIn fetch → company website → careers page → jobs list) populate live,
or switch to the **Batch test** tab to run several URLs at once and see a summary chip
(success rate, average time) plus a per-URL results table.

### API

- `GET /healthz` → `{"ok": true}`
- `POST /resolve` — body `{"url": "<linkedin_url>"}`, returns the full pipeline result
  (see shape above).
- `GET /resolve/stream?url=<linkedin_url>` — Server-Sent Events; one named event per
  stage (`linkedin_fetch`, `company_website`, `careers_page`, `jobs_list`), plus a final
  `done` event with the aggregated result.
- `POST /batch` — body `{"urls": ["...", "..."]}`, resolves all URLs concurrently
  (max 5 at once), returns `{"results": [...], "summary": {"total", "succeeded",
  "failed", "success_rate", "avg_elapsed_ms"}}`.

```bash
curl -X POST localhost:8000/resolve \
  -H 'content-type: application/json' \
  -d '{"url":"https://www.linkedin.com/jobs/view/4427787182/"}'

curl -X POST localhost:8000/batch \
  -H 'content-type: application/json' \
  -d '{"urls":["https://www.linkedin.com/jobs/view/4427787182/","https://www.linkedin.com/jobs/view/1111111111/"]}'
```

### Test harness

Put one LinkedIn job URL per line in `data/test_urls.txt` (lines starting with `#` are
ignored), then run:

```bash
python scripts/test_harness.py
```

This resolves every URL, prints a per-URL status line and a final success-rate summary,
and writes results to `data/results.csv`. Use `--input`, `--output`, or `--headed` to
override the URL list, output path, or run with a visible browser window for debugging.
It calls the exact same `resolve_job_listing_url` used by the API, so harness numbers and
API responses never diverge.

## Deploy to Render

1. Push this repo to GitHub (see commands below).
2. On [Render](https://render.com), **New → Blueprint**, connect the repo — `render.yaml`
   configures the free Docker web service automatically.
3. Set the `GROQ_API_KEY` environment variable in the Render dashboard (it's marked
   `sync: false` in `render.yaml`, so Render will prompt for it rather than expecting it
   in the repo).
4. Render builds the `Dockerfile` (Playwright's official image, Chromium preinstalled —
   no `playwright install` needed at build or runtime) and health-checks `/healthz`.

### Docker locally

```bash
docker build -t jobnova .
docker run -p 8000:8000 -e GROQ_API_KEY=$GROQ_API_KEY jobnova
```

## Pipeline

1. **`job_agent/linkedin_scraper.py`** — renders the LinkedIn job page and extracts the
   company name (preferring the page's embedded `schema.org/JobPosting` JSON-LD, falling
   back to the topcard DOM) and the company's LinkedIn URL. Distinguishes a real block
   (redirect to `/authwall`, `/checkpoint/`, `/uas/login`, or a CAPTCHA) from ordinary
   anonymous-visitor page chrome, and reports blocks as a structured failure rather than
   crashing.
2. **`job_agent/website_resolver.py`** — reads the official website from the company's
   LinkedIn `/about/` page's "Website" field. In practice LinkedIn requires login to view
   that page, so this step routinely falls through to its DuckDuckGo search fallback
   (`"<company> official website"`, first non-social result) — this is expected, not a bug.
3. **`job_agent/careers_finder.py`** — scans the homepage's `nav`/`footer` links for
   careers-related keywords. When multiple links score equally (genuine ambiguity), the
   shortlist is sent to the Groq tiebreaker (`job_agent/llm_tiebreaker.py`); otherwise the
   top-scoring link wins outright and Groq is never called. If no candidates are found,
   falls back to a `site:<domain> careers` DuckDuckGo search.
4. **`job_agent/ats_detector.py`** — follows redirects on the discovered careers page and
   checks the final domain against the known ATS list.
5. **`job_agent/llm_tiebreaker.py`** — sends a short JSON shortlist (`{"text", "url"}`
   pairs) to Groq's `llama-3.3-70b-versatile` and asks for a single URL back. Returns
   `None` on any failure or missing API key, so callers always have a safe fallback.
6. **`job_agent/pipeline.py`** — `run_pipeline_stages()` is a generator that runs steps
   1–4 in order inside one Playwright browser session, yielding a `StageEvent` as each
   completes; `resolve_job_listing_url()` consumes it into the full result dict used by
   the harness and every API endpoint (`summarize()` builds that same dict from a partial
   or complete stage list, so the SSE endpoint's closing event matches `/resolve` exactly).
   Any stage exception is caught and reported as a structured failure rather than crashing.

## Known limitations

- LinkedIn's public "guest" view only covers job posting pages — company `/about/` pages
  require login, so step 2 usually relies on its DuckDuckGo fallback rather than the
  About panel.
- LinkedIn's DOM/CSS class names change periodically; the JSON-LD extraction path is the
  more durable of the two extraction strategies in `linkedin_scraper.py`.
- **The DuckDuckGo website-search fallback can be non-deterministic for ambiguous company
  names.** E.g. "Harvey" (the AI legal tech company) sometimes resolves to
  `steveharvey.com` instead of `harvey.ai`, purely from search-ranking variance run to
  run — same query, different top result. This lives in `website_resolver.py`.
- `playwright` is pinned to `1.47.0` in `requirements.txt` to match the Chromium build
  baked into the `mcr.microsoft.com/playwright/python:v1.47.0-jammy` Docker image. If you
  bump the Dockerfile's base image tag, bump this pin to match, or Chromium launch will
  fail at runtime with an executable-not-found error.

## Push to GitHub

```bash
gh repo create jobnova-source-agent --private --source=. --remote=origin
git push -u origin main
```

(Or without `gh`: create an empty repo on GitHub, then
`git remote add origin <url> && git push -u origin main`.)
