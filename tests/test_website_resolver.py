"""Unit tests for the website-resolver scoring layer.

Pure function, no network calls (page_text is left as None, which just skips
the +2 title/h1 signal) — safe for pytest to collect and run automatically.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from job_agent.website_resolver import score_candidate

SLUG = "harvey"
DISPLAY_NAME = "Harvey"


def test_exact_domain_match_scores_plus_five():
    assert score_candidate("https://harvey.ai", SLUG, DISPLAY_NAME) == 5


def test_blocklisted_lookalike_scores_minus_five():
    # steveharvey.com contains "harvey" as a substring, which is exactly why
    # it needs to be blocklisted rather than left to string-overlap scoring.
    assert score_candidate("https://steveharvey.com", SLUG, DISPLAY_NAME) == -5


def test_substring_match_scores_plus_three():
    assert score_candidate("https://harveynichols.com", SLUG, DISPLAY_NAME) == 3


def test_blocklisted_subdomain_scores_minus_five():
    # registered domain is wikipedia.org (harvey is just the subdomain) —
    # blocklist matching must be on the registered domain, not the full host.
    assert score_candidate("https://harvey.wikipedia.org", SLUG, DISPLAY_NAME) == -5


def test_real_world_slug_with_suffix_still_matches():
    # The scraper's actual slugs look like "harvey-ai", not the bare "harvey"
    # used above — normalization must still resolve this to a +5 match.
    assert score_candidate("https://harvey.ai", "harvey-ai", DISPLAY_NAME) == 5


def test_unrelated_domain_scores_zero():
    assert score_candidate("https://example.com", SLUG, DISPLAY_NAME) == 0


def test_news_article_path_is_penalized():
    score_home = score_candidate("https://harveynichols.com", SLUG, DISPLAY_NAME)
    score_article = score_candidate("https://harveynichols.com/news/2024/some-story", SLUG, DISPLAY_NAME)
    assert score_article == score_home - 3
