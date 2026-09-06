from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError, Page

ATS_DOMAINS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkday.com",
    "smartrecruiters.com",
    "workable.com",
    "jobvite.com",
)


def detect_ats_or_final_url(page: Page, careers_url: str) -> str:
    try:
        page.goto(careers_url, wait_until="domcontentloaded", timeout=30_000)
        return page.url
    except PlaywrightError:
        return careers_url


def is_known_ats(url: str) -> bool:
    hostname = urlparse(url).netloc.lower().removeprefix("www.")
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in ATS_DOMAINS)
