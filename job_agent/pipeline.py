"""Pipeline orchestration.

This is the single source of truth for running the four resolution stages in
order. `run_pipeline_stages` is a plain, synchronous generator (Playwright's
sync API drives every stage module, so this stays synchronous) that yields a
`StageEvent` as each stage finishes. `resolve_job_listing_url` consumes that
generator and is the shared entry point used by the CLI test harness
(scripts/test_harness.py), the FastAPI JSON endpoints (/resolve, /batch), and
the SSE endpoint (/resolve/stream) — none of them duplicate the pipeline
order, they just consume it differently (whole result vs. one stage at a time).

Each call to run_pipeline_stages() creates its own generator with its own
local variables, so concurrent callers (e.g. /batch running several of these
in parallel threads) never share mutable state.
"""

import time
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlparse

from .ats_detector import ATS_DOMAINS, detect_ats_or_final_url, is_known_ats
from .browser import chromium_page
from .careers_finder import find_careers_page
from .linkedin_scraper import scrape_job_details
from .website_resolver import resolve_company_website

STAGE_NAMES = ("linkedin_fetch", "company_website", "careers_page", "jobs_list")


@dataclass
class StageEvent:
    stage: str
    status: str  # "success" | "error"
    value: str | None = None
    error: str | None = None
    elapsed_ms: int | None = None
    extra: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "value": self.value,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
        }


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def run_pipeline_stages(linkedin_job_url: str, headless: bool = True) -> Iterator[StageEvent]:
    """Run the pipeline one stage at a time, yielding a StageEvent as each completes.

    Stops after the first failing stage, since every later stage depends on
    the previous one's output.
    """
    with chromium_page(headless=headless) as page:
        start = time.monotonic()
        try:
            details = scrape_job_details(page, linkedin_job_url)
        except Exception as error:
            yield StageEvent("linkedin_fetch", "error", error=str(error), elapsed_ms=_elapsed_ms(start))
            return
        yield StageEvent(
            "linkedin_fetch",
            "success",
            value=details["company_name"],
            elapsed_ms=_elapsed_ms(start),
            extra={"company_linkedin_url": details["company_linkedin_url"]},
        )

        start = time.monotonic()
        try:
            website = resolve_company_website(page, details["company_name"], details["company_linkedin_url"])
        except Exception as error:
            yield StageEvent("company_website", "error", error=str(error), elapsed_ms=_elapsed_ms(start))
            return
        yield StageEvent("company_website", "success", value=website, elapsed_ms=_elapsed_ms(start))

        start = time.monotonic()
        try:
            careers_page = find_careers_page(page, website)
        except Exception as error:
            yield StageEvent("careers_page", "error", error=str(error), elapsed_ms=_elapsed_ms(start))
            return
        yield StageEvent("careers_page", "success", value=careers_page, elapsed_ms=_elapsed_ms(start))

        start = time.monotonic()
        try:
            final_url = detect_ats_or_final_url(page, careers_page)
        except Exception as error:
            yield StageEvent("jobs_list", "error", error=str(error), elapsed_ms=_elapsed_ms(start))
            return
        yield StageEvent("jobs_list", "success", value=final_url, elapsed_ms=_elapsed_ms(start))


def ats_platform_for(url: str | None) -> str | None:
    if not url:
        return None
    hostname = urlparse(url).netloc.lower().removeprefix("www.")
    for domain in ATS_DOMAINS:
        if hostname == domain or hostname.endswith(f".{domain}"):
            return domain
    return None


def summarize(linkedin_job_url: str, events: list[StageEvent]) -> dict:
    """Build the aggregated result dict from a (possibly partial, if it
    stopped early on a stage error) list of StageEvents.

    This is the single place that turns "what happened stage by stage" into
    the API response shape, so resolve_job_listing_url (used by /resolve and
    /batch) and the SSE handler's closing "done" event (which streams stages
    as they happen rather than collecting them upfront) never disagree.
    """
    values: dict[str, str | None] = dict.fromkeys(STAGE_NAMES)
    company_linkedin_url: str | None = None
    status = "failure"
    reason: str | None = None
    errors: list[str] = []

    for event in events:
        if event.status == "error":
            reason = event.error
            errors.append(event.stage)
            break
        values[event.stage] = event.value
        if event.stage == "linkedin_fetch" and event.extra:
            company_linkedin_url = event.extra.get("company_linkedin_url")

    jobs_list_url = values["jobs_list"]
    platform = ats_platform_for(jobs_list_url)
    if jobs_list_url:
        status = "success"
        reason = "Resolved to a known ATS job-listings page" if is_known_ats(jobs_list_url) else "Resolved to the company's careers page"

    return {
        "linkedin_job_url": linkedin_job_url,
        "company_name": values["linkedin_fetch"],
        "company_linkedin_url": company_linkedin_url,
        "company_website": values["company_website"],
        "careers_page_url": values["careers_page"],
        "jobs_list_url": jobs_list_url,
        "ats_platform": platform,
        "status": status,
        "reason": reason,
        "errors": errors,
    }


def resolve_job_listing_url(linkedin_job_url: str, headless: bool = True) -> dict:
    """Run the full pipeline and return the aggregated result as a dict.

    Shared by the CLI harness and every API endpoint — see module docstring.
    """
    start = time.monotonic()
    events = list(run_pipeline_stages(linkedin_job_url, headless=headless))
    result = summarize(linkedin_job_url, events)
    result["stages"] = [event.as_dict() for event in events]
    result["elapsed_ms"] = _elapsed_ms(start)
    return result
