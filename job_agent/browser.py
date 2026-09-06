from contextlib import contextmanager
from random import choice, uniform
from time import sleep
from typing import Iterator

from playwright.sync_api import Browser, Page, sync_playwright


USER_AGENTS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
)


def polite_delay(min_seconds: float = 0.8, max_seconds: float = 2.0) -> None:
    sleep(uniform(min_seconds, max_seconds))


@contextmanager
def chromium_page(headless: bool = True) -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=choice(USER_AGENTS), locale="en-US")
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()
