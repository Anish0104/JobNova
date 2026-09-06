from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass
class JobResolution:
    linkedin_job_url: str
    company_name: str | None = None
    company_linkedin_url: str | None = None
    company_website_url: str | None = None
    careers_page_url: str | None = None
    final_job_listings_url: str | None = None
    status: str = "failure"
    reason: str | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "linkedin_job_url": self.linkedin_job_url,
            "company_name": self.company_name,
            "company_linkedin_url": self.company_linkedin_url,
            "company_website_url": self.company_website_url,
            "careers_page_url": self.careers_page_url,
            "final_job_listings_url": self.final_job_listings_url,
            "status": self.status,
            "reason": self.reason,
            "errors": self.errors,
        }


def is_http_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
