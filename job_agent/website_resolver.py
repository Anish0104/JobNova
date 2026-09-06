from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError, Page

from .browser import polite_delay
from .models import is_http_url

_SOCIAL_HOSTS = {"linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com"}


def resolve_company_website(
    page: Page,
    company_name: str,
    company_linkedin_url: str | None,
) -> str:
    if company_linkedin_url:
        about_url = company_linkedin_url.rstrip("/") + "/about/"
        try:
            page.goto(about_url, wait_until="domcontentloaded", timeout=30_000)
            polite_delay()
            soup = BeautifulSoup(page.content(), "lxml")

            website = _website_from_about_panel(soup)
            if website:
                return website.rstrip("/")

            for anchor in soup.select("a[href]"):
                href = anchor.get("href")
                if _is_candidate(href):
                    return href.rstrip("/")
        except PlaywrightError:
            pass

    return _search_official_website(company_name)


def _website_from_about_panel(soup: BeautifulSoup) -> str | None:
    for dt in soup.find_all("dt"):
        if "website" not in dt.get_text(strip=True).lower():
            continue
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        anchor = dd.find("a", href=True)
        href = anchor["href"] if anchor else dd.get_text(strip=True)
        if _is_candidate(href):
            return href
    return None


def _search_official_website(company_name: str) -> str:
    try:
        from ddgs import DDGS

        query = f"{company_name} official website"
        for result in DDGS().text(query, max_results=8):
            href = result.get("href") or result.get("link")
            if _is_candidate(href):
                return href.rstrip("/")
    except Exception as error:
        raise RuntimeError(f"Official website search failed: {error}") from error
    raise RuntimeError("Could not find an official company website")


def _is_candidate(href: str | None) -> bool:
    if not is_http_url(href):
        return False
    host = urlparse(href).netloc.lower().removeprefix("www.")
    return not any(host == social or host.endswith(f".{social}") for social in _SOCIAL_HOSTS)
