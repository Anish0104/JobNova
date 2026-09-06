import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError, Page

from .browser import polite_delay
from .models import is_http_url

# Markers that only appear when LinkedIn actually redirects to a wall or challenge,
# not generic nav chrome like "Sign in" which is present on every anonymous page view.
_BLOCK_URL_MARKERS = ("/authwall", "/checkpoint/", "/uas/login")
_BLOCK_TEXT_MARKERS = ("please verify you're a human", "let's do a quick security check")
_LINKEDIN_COMPANY_PATTERN = re.compile(r"https?://(?:www\.)?linkedin\.com/company/[^/?#]+", re.I)
_TOPCARD_SELECTOR = ".topcard__org-name-link, a[data-tracking-control-name='public_jobs_topcard-org-name']"


def scrape_job_details(page: Page, linkedin_job_url: str) -> dict[str, str | None]:
    if not is_http_url(linkedin_job_url) or "linkedin.com/jobs/" not in linkedin_job_url:
        raise ValueError("Expected a LinkedIn job posting URL")

    try:
        page.goto(linkedin_job_url, wait_until="domcontentloaded", timeout=30_000)
        polite_delay()
        current_url = page.url.lower()
        if any(marker in current_url for marker in _BLOCK_URL_MARKERS):
            raise RuntimeError("LinkedIn blocked the request or requires authentication")

        body_text = page.locator("body").inner_text(timeout=10_000).lower()
        if any(marker in body_text for marker in _BLOCK_TEXT_MARKERS):
            raise RuntimeError("LinkedIn blocked the request or requires authentication")

        soup = BeautifulSoup(page.content(), "lxml")

        company_name, company_linkedin_url = _from_json_ld(soup)
        if not company_name:
            company_name = _first_topcard_text(soup)
        if not company_linkedin_url:
            company_linkedin_url = _company_link(soup, page.url)

        if not company_name:
            raise RuntimeError("Could not find the company name on the LinkedIn job page")
        return {"company_name": company_name.strip(), "company_linkedin_url": company_linkedin_url}
    except PlaywrightError as error:
        raise RuntimeError(f"LinkedIn page could not be loaded: {error}") from error


def _from_json_ld(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                continue
            org = item.get("hiringOrganization")
            if not isinstance(org, dict):
                continue
            name = org.get("name")
            same_as = org.get("sameAs") or org.get("url")
            company_url = same_as if isinstance(same_as, str) and _LINKEDIN_COMPANY_PATTERN.search(same_as) else None
            if name:
                return name, company_url
    return None, None


def _first_topcard_text(soup: BeautifulSoup) -> str | None:
    for selector in (".topcard__org-name-link", "a[data-tracking-control-name='public_jobs_topcard-org-name']"):
        tag = soup.select_one(selector)
        if tag:
            text = tag.get_text(strip=True)
            if text:
                return text
    return None


def _company_link(soup: BeautifulSoup, base_url: str) -> str | None:
    topcard_anchor = soup.select_one(_TOPCARD_SELECTOR)
    if topcard_anchor and topcard_anchor.get("href"):
        match = _LINKEDIN_COMPANY_PATTERN.search(urljoin(base_url, topcard_anchor["href"]))
        if match:
            return match.group(0)

    for anchor in soup.select("a[href]"):
        match = _LINKEDIN_COMPANY_PATTERN.search(urljoin(base_url, anchor.get("href", "")))
        if match:
            return match.group(0)
    return None
