"""LinkedIn Job Source Agent package."""

from pathlib import Path

from dotenv import load_dotenv

# Explicit path, not dotenv's default stack-walking search: this makes
# .env loading independent of the caller's CWD or call stack shape.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .pipeline import resolve_job_listing_url

__all__ = ["resolve_job_listing_url"]
