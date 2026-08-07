from __future__ import annotations
"""Jobstreet Philippines — uses the official SEEK/Jobstreet v5 search API.
No API key required. Returns structured JSON job listings from ph.jobstreet.com.

The API endpoint is discovered from the page's SEEK_CONFIG:
  /api/jobsearch/v5/search
"""

import httpx
from sources.base import BaseSource
from core.models import Job

RESULTS_PER_QUERY = 30

DEFAULT_QUERIES = [
    "python developer",
    "backend developer",
    "software engineer",
    "django developer",
    "fastapi developer",
]


class JobstreetSource(BaseSource):
    name = "jobstreet"
    BASE_URL = "https://ph.jobstreet.com/api/jobsearch/v5/search"

    async def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://ph.jobstreet.com/",
            "Origin": "https://ph.jobstreet.com",
        }

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for query in DEFAULT_QUERIES:
                try:
                    params = {
                        "siteKey": "PH-Main",
                        "sourcesystem": "houston",
                        "where": "Philippines",
                        "page": "1",
                        "keywords": query,
                        "include": "seodata",
                        "locale": "en-PH",
                        "pageSize": str(RESULTS_PER_QUERY),
                        "seekSelectAllPages": "true",
                    }

                    resp = await client.get(
                        self.BASE_URL, headers=headers, params=params
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()

                    # The v5 API nests jobs under data[] or jobs[]
                    items = data.get("data", data.get("jobs", []))
                    for item in items:
                        job_id = str(item.get("id", ""))
                        if not job_id or job_id in seen_ids:
                            continue
                        seen_ids.add(job_id)

                        # Flatten listing vs root-level fields
                        listing = item.get("listing", item)

                        # Location
                        locations = listing.get("locations", [])
                        if locations:
                            loc = locations[0]
                            area = (loc.get("area") or {}).get("label", "")
                            region = (loc.get("location") or {}).get("label", "Philippines")
                            location = f"{area}, {region}".strip(", ") if area else region
                        else:
                            location = listing.get("location", "Philippines")

                        # Salary
                        salary = ""
                        sal = listing.get("salary", {}) or {}
                        mn = sal.get("minimum") or sal.get("min")
                        mx = sal.get("maximum") or sal.get("max")
                        currency = sal.get("currency", "PHP")
                        period = sal.get("type", sal.get("period", ""))
                        if mn and mx:
                            salary = f"{currency} {mn:,.0f} - {mx:,.0f} / {period}"
                        elif mn:
                            salary = f"{currency} {mn:,.0f}+ / {period}"

                        # Job URL
                        job_url = (
                            listing.get("shareLink")
                            or listing.get("applyLink")
                            or f"https://ph.jobstreet.com/job/{job_id}"
                        )

                        # Tech tags
                        tags = listing.get("tags", []) or []
                        tech = ", ".join(
                            t.get("label", "") for t in tags if t.get("label")
                        )

                        job = Job(
                            title=listing.get("title", ""),
                            company=(
                                (listing.get("advertiser") or {}).get("description", "")
                                or listing.get("companyName", "")
                            ),
                            location=location,
                            description=(
                                listing.get("teaser", "")
                                or listing.get("summary", "")
                            ),
                            url=job_url,
                            source=self.name,
                            posted_date=(
                                listing.get("listedAt", "")
                                or listing.get("listingDate", "")
                            ),
                            salary=salary,
                            job_type=listing.get("workType", ""),
                            tech_stack=tech,
                        )
                        jobs.append(job)

                except Exception:
                    continue

        return jobs
