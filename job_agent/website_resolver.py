"""Resolves a company's official website.

Primary path: read the "Website" field from the company's public LinkedIn
about page (works when LinkedIn doesn't gate it behind login).

Fallback: DuckDuckGo search + a validation/scoring layer. DDG's #1 result
alone is not reliable for generic company names — e.g. "Harvey" (the AI
legal tech company) frequently returns steveharvey.com as the top hit, and
that's not a one-off: rerunning the same query can flip the top result
between runs. Instead of trusting rank 1, we pull several candidates and
score each against the LinkedIn company slug and display name, only
returning a candidate whose score clears a confidence bar.
"""

import re
from functools import lru_cache
from urllib.parse import urlparse

import httpx
import tldextract
from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError, Page

from .browser import polite_delay
from .models import is_http_url

_SOCIAL_HOSTS = {"linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com"}

# Domains that reliably outrank the real company site for generic/celebrity
# -adjacent names, reference sites, and social/data aggregators that show up
# constantly as false positives regardless of query wording.
_BLOCKLIST = {
    "steveharvey.com", "imdb.com", "wikipedia.org", "linkedin.com",
    "facebook.com", "twitter.com", "x.com", "youtube.com", "crunchbase.com",
    "glassdoor.com", "bloomberg.com", "forbes.com", "reuters.com",
}

# LinkedIn slugs are often "<name>-<generic suffix>" (e.g. "harvey-ai" for a
# company whose actual domain is harvey.ai). Stripping a trailing/leading
# suffix like this lets the slug still match the domain's second-level label.
_SLUG_SUFFIXES = {
    "ai", "io", "so", "hq", "inc", "co", "corp", "labs", "technologies",
    "tech", "app", "dev", "group", "global", "official", "team",
}

_ARTICLE_PATH_MARKERS = ("/article/", "/articles/", "/news/", "/blog/", "/press/", "/story/")
_YEAR_IN_PATH = re.compile(r"/(19|20)\d{2}/")

# Boilerplate that domain-parking/marketplace pages use — relevant because
# this resolver also tries guessed domains directly, and an unregistered
# guess resolving to a "for sale" page is not evidence it's the right site.
_PARKED_MARKERS = (
    "domain for sale", "this domain is for sale", "buy this domain",
    "this domain is parked", "domain is parked", "spaceship.com",
    "godaddy", "sedo.com", "hugedomains", "afternic", "namecheap",
    "dan.com",
)

# Offline snapshot only — no live public-suffix-list fetch on every call.
_extract = tldextract.TLDExtract(suffix_list_urls=())


def resolve_company_website(
    page: Page,
    company_name: str,
    company_linkedin_url: str | None,
) -> str:
    if company_linkedin_url:
        website = _website_from_linkedin_about(page, company_linkedin_url)
        if website:
            return website

    slug = _slug_from_linkedin_url(company_linkedin_url)
    website = _search_and_score(slug, company_name)
    if not website:
        raise RuntimeError("Could not confidently determine an official company website")
    return website


def _website_from_linkedin_about(page: Page, company_linkedin_url: str) -> str | None:
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
    return None


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


def _slug_from_linkedin_url(company_linkedin_url: str | None) -> str:
    if not company_linkedin_url:
        return ""
    parts = [p for p in urlparse(company_linkedin_url).path.split("/") if p]
    if "company" in parts:
        index = parts.index("company")
        if index + 1 < len(parts):
            return parts[index + 1]
    return parts[-1] if parts else ""


# For a short/generic company name (exactly the case that started this —
# "Harvey"), DDG's top 10 results for "<name> official website" can be
# *entirely* unrelated Harveys (celebrities, musicians, a department store)
# with the real domain not appearing anywhere in them at all. No amount of
# re-ranking search results fixes a candidate that was never returned, so we
# also validate a handful of domains guessed directly from the LinkedIn slug
# — which is exactly where "harvey-ai" as a slug pays off: stripping "ai" as
# a generic suffix (for label-matching) also makes it a TLD worth trying.
_GUESS_TLDS = ("com", "ai", "io")


def _guessed_domains(slug: str) -> list[str]:
    guesses: list[str] = []
    for variant in _slug_variants(slug):
        for tld in _GUESS_TLDS:
            guesses.append(f"{variant}.{tld}")
    return guesses


@lru_cache(maxsize=256)
def _search_and_score(slug: str, display_name: str) -> str | None:
    """Validated-guess + DuckDuckGo fallback, cached by (slug, display_name)
    so repeated resolutions in the same process are deterministic rather
    than "usually right". A raised exception (e.g. the search itself fails)
    is never cached — only a successful lookup, hit or miss, is.
    """
    candidates: dict[str, tuple[str, str | None]] = {}  # registered domain -> (url, page_text)

    for domain in _guessed_domains(slug):
        url = f"https://{domain}"
        registered = _registered_domain(url)
        if not registered or registered in _BLOCKLIST or registered in candidates:
            continue
        page_text = _fetch_title_and_h1(url)
        if page_text is not None:  # guess actually resolves to a live site
            candidates[registered] = (url, page_text)

    try:
        from ddgs import DDGS

        raw_results = list(DDGS().text(f"{display_name} official website", max_results=10))
    except Exception as error:
        if not candidates:
            raise RuntimeError(f"Official website search failed: {error}") from error
        raw_results = []  # domain guesses alone may still be enough

    for result in raw_results:
        href = result.get("href") or result.get("link")
        if not _is_candidate(href):
            continue
        registered = _registered_domain(href)
        if registered and registered not in candidates and registered not in _BLOCKLIST:
            candidates[registered] = (href, None)  # page_text fetched lazily below

    # Rank by (score, -label length) rather than raw insertion order: ties are
    # real (a parked-but-guessed domain can score identically to the correct
    # one before the parked-page penalty below applies) and dict iteration
    # order for candidates built from a set of slug variants is not stable
    # across processes (string hash randomization), so relying on "first one
    # wins" would make the result non-deterministic in exactly the way this
    # whole fix exists to eliminate. Preferring the shorter label breaks ties
    # toward the more canonical-looking domain (harvey.ai over harveyai.com).
    best_url: str | None = None
    best_key: tuple[int, int] | None = None
    for registered, (url, page_text) in candidates.items():
        if page_text is None:
            page_text = _fetch_title_and_h1(url)
        score = score_candidate(url, slug, display_name, page_text=page_text)
        key = (score, -len(_extract(url).domain))
        if best_key is None or key > best_key:
            best_key, best_url = key, url

    if best_url is None or best_key[0] < 3:
        return None
    return best_url.rstrip("/")


def score_candidate(url: str, slug: str, display_name: str, page_text: str | None = None) -> int:
    """Score how likely `url` is to be the company's real homepage.

    Blocklisted domains short-circuit to a flat -5 regardless of any string
    overlap with the slug — that overlap is exactly what makes them dangerous
    false positives (steveharvey.com contains "harvey"), so a diluted score
    that a strong overlap could still push positive would defeat the point.
    """
    ext = _extract(url)
    if not ext.domain or not ext.suffix:
        return 0

    registered = f"{ext.domain}.{ext.suffix}".lower()
    if registered in _BLOCKLIST:
        return -5

    label = ext.domain.lower()
    slug_variants = _slug_variants(slug)

    score = 0
    if slug_variants and label in slug_variants:
        score += 5
    elif slug_variants and any(variant in label for variant in slug_variants):
        score += 3

    if page_text:
        if _looks_parked(page_text):
            # A guessed domain that merely resolves is not evidence of
            # anything — plenty of unregistered-but-guessable domains are
            # just parked for sale, and a parking page's boilerplate can
            # coincidentally contain the company name (e.g. "harveyai.com
            # for sale" contains "harvey"). Treat that as a strong negative,
            # not a title match.
            score -= 6
        elif _name_tokens_present(display_name, page_text):
            score += 2

    path = urlparse(url).path.lower()
    if any(marker in path for marker in _ARTICLE_PATH_MARKERS) or _YEAR_IN_PATH.search(path):
        score -= 3

    return score


def _slug_variants(slug: str) -> list[str]:
    """Deterministic order matters: callers iterate this to build guessed
    domains, and that iteration order must not depend on string hash
    randomization (a plain set's iteration order varies per process)."""
    tokens = [token for token in re.split(r"[^a-z0-9]+", (slug or "").lower()) if token]
    if not tokens:
        return []

    ordered = [t for t in ["".join(tokens)] if t]
    if len(tokens) > 1 and tokens[-1] in _SLUG_SUFFIXES:
        ordered.append("".join(tokens[:-1]))
    if len(tokens) > 1 and tokens[0] in _SLUG_SUFFIXES:
        ordered.append("".join(tokens[1:]))

    seen: set[str] = set()
    deduped = []
    for variant in ordered:
        if variant and variant not in seen:
            seen.add(variant)
            deduped.append(variant)
    return deduped


def _name_tokens_present(display_name: str, page_text: str) -> bool:
    tokens = [token for token in re.split(r"[^a-zA-Z0-9]+", display_name.lower()) if len(token) > 2]
    haystack = page_text.lower()
    return any(token in haystack for token in tokens)


def _looks_parked(page_text: str) -> bool:
    haystack = page_text.lower()
    return any(marker in haystack for marker in _PARKED_MARKERS)


def _fetch_title_and_h1(url: str) -> str | None:
    try:
        response = httpx.get(url, timeout=3.0, follow_redirects=True)
        soup = BeautifulSoup(response.text, "lxml")
        title = soup.title.get_text(strip=True) if soup.title else ""
        h1 = soup.find("h1")
        combined = f"{title} {h1.get_text(strip=True) if h1 else ''}".strip()
        return combined or None
    except Exception:
        return None


def _registered_domain(url: str | None) -> str | None:
    if not is_http_url(url):
        return None
    ext = _extract(url)
    if not ext.domain or not ext.suffix:
        return None
    return f"{ext.domain}.{ext.suffix}".lower()


def _is_candidate(href: str | None) -> bool:
    if not is_http_url(href):
        return False
    host = urlparse(href).netloc.lower().removeprefix("www.")
    return not any(host == social or host.endswith(f".{social}") for social in _SOCIAL_HOSTS)
