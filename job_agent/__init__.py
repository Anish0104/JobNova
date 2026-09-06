"""LinkedIn Job Source Agent package."""

from dotenv import load_dotenv

load_dotenv()

from .pipeline import resolve_job_listing_url

__all__ = ["resolve_job_listing_url"]
