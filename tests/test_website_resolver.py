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


# --- No-separator slug suffix stripping ("unwrapai" -> unwrap.ai) ---


def test_no_separator_slug_suffix_strip_matches_exactly():
    # "unwrapai" has no hyphen, so token-based suffix stripping alone can't
    # reduce it to "unwrap" — this needs the plain-string suffix strip.
    assert score_candidate("https://unwrap.ai", "unwrapai", "Unwrap") == 5


def test_no_separator_slug_suffix_strip_does_not_match_unrelated_domain():
    # The stripped suffix itself ("ai") must not become a viable variant on
    # its own — a candidate whose label is just "ai" should not benefit from
    # matching the remnant of a stripped suffix.
    assert score_candidate("https://ai.com", "unwrapai", "Unwrap") == 0


# --- Reverse (label-is-prefix-of-slug) matching ("anthropicresearch" -> anthropic.com) ---


def test_label_prefix_of_legacy_slug_scores_plus_three():
    # "anthropicresearch" is Anthropic's real LinkedIn slug (legacy name),
    # with "anthropic" as a strict prefix — no amount of suffix stripping
    # turns "research" into a known generic suffix, so this needs the
    # reverse (label-is-prefix-of-slug) direction specifically.
    assert score_candidate("https://anthropic.com", "anthropicresearch", "Anthropic") == 3


def test_label_substring_but_not_prefix_of_slug_does_not_match():
    # "research" is also a substring of "anthropicresearch", just not the
    # brand-name prefix — this must NOT score like a real candidate, or any
    # word appearing anywhere in a slug could false-positive.
    assert score_candidate("https://research.com", "anthropicresearch", "Anthropic") == 0
