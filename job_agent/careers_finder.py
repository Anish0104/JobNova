from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError, Page

from .browser import polite_delay
from .llm_tiebreaker import pick_careers_link
from .models import is_http_url

CAREERS_KEYWORDS = ("career", "job", "join us", "we're hiring", "work with us", "vacanc")


def find_careers_page(page: Page, website_url: str) -> str:
    try:
        page.goto(website_url, wait_until="domcontentloaded", timeout=30_000)
        polite_delay()
        soup = BeautifulSoup(page.content(), "lxml")
        candidates = _candidate_links(soup, website_url)
        if candidates:
            return _choose_candidate(candidates)
    except PlaywrightError:
        pass
    return _search_careers_page(website_url)


def _candidate_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for anchor in soup.select("nav a[href], footer a[href]"):
        href = urljoin(base_url, anchor.get("href", ""))
        if not is_http_url(href):
            continue
        text = anchor.get_text(" ", strip=True)
        haystack = f"{text} {href}".lower()
        score = sum(keyword in haystack for keyword in CAREERS_KEYWORDS)
        if score and (href not in seen or score > seen[href]["score"]):
            seen[href] = {"text": text or href, "url": href, "score": score}
    return sorted(seen.values(), key=lambda candidate: candidate["score"], reverse=True)


def _choose_candidate(candidates: list[dict]) -> str:
    if len(candidates) == 1 or candidates[0]["score"] > candidates[1]["score"]:
        return candidates[0]["url"]

    # Genuine ambiguity: multiple links score equally well on keywords alone
    # (e.g. a "life at <company>" blog post vs. the real careers page).
    shortlist = [{"text": c["text"], "url": c["url"]} for c in candidates[:5]]
    return pick_careers_link(shortlist) or candidates[0]["url"]


def _search_careers_page(website_url: str) -> str:
    from ddgs import DDGS

    domain = website_url.split("//", 1)[-1].split("/", 1)[0]
    query = f"site:{domain} careers"
    for result in DDGS().text(query, max_results=8):
        href = result.get("href") or result.get("link")
        if is_http_url(href):
            return href
    raise RuntimeError("Could not find a careers page")
