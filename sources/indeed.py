from __future__ import annotations
"""Indeed Philippines — scrapes ph.indeed.com using the mosaic job cards JSON.
No API key required.

Notes on reliability:
  - Indeed embeds structured job data in a window.mosaic.providerData script.
  - A two-step request (home page first to collect cookies, then search) is used
    to reduce bot-detection false positives.
  - If Indeed blocks the IP, this source will log 0 jobs — that is expected
    behaviour and is not a bug. Consider using Jobstreet (always works) as the
    primary PH source.
"""

import asyncio
import json
import random
import re
import httpx
from sources.base import BaseSource
from core.models import Job

RESULTS_PER_QUERY = 15

DEFAULT_QUERIES = [
    "python developer",
    "backend developer",
    "software engineer",
    "django developer",
]

_BASE = "https://ph.indeed.com"
_SEARCH = f"{_BASE}/jobs"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class IndeedPHSource(BaseSource):
    name = "indeed_ph"

    async def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        # Use a persistent client so cookies are preserved across requests
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, http2=False
        ) as client:
            # Step 1: warm up session with homepage visit
            try:
                await client.get(_BASE, headers=_HEADERS)
                await asyncio.sleep(random.uniform(1.0, 2.0))
            except Exception:
                pass

            for query in DEFAULT_QUERIES:
                try:
                    params = {
                        "q": query,
                        "l": "Philippines",
                        "sort": "date",
                        "fromage": "14",
                        "limit": str(RESULTS_PER_QUERY),
                    }
                    resp = await client.get(
                        _SEARCH, headers=_HEADERS, params=params
                    )

                    if resp.status_code not in (200, 304):
                        continue

                    self._extract_jobs(resp.text, jobs, seen_ids)
                    await asyncio.sleep(random.uniform(1.5, 3.0))

                except Exception:
                    continue

        return jobs

    def _extract_jobs(
        self,
        html: str,
        jobs: list[Job],
        seen_ids: set[str],
    ) -> None:
        """Extract from the window.mosaic.providerData JSON blob."""
        # Indeed embeds the full job list in a script tag
        match = re.search(
            r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});\s*window',
            html,
            re.DOTALL,
        )
        if match:
            try:
                data = json.loads(match.group(1))
                results = (
                    data
                    .get("metaData", {})
                    .get("mosaicProviderJobCardsModel", {})
                    .get("results", [])
                )
                for item in results:
                    jk = item.get("jobkey") or item.get("jobKey", "")
                    if not jk or jk in seen_ids:
                        continue
                    seen_ids.add(jk)

                    location = item.get("formattedLocation", "Philippines")
                    if location and "philippines" not in location.lower():
                        location = f"{location}, Philippines"

                    jobs.append(Job(
                        title=item.get("title", ""),
                        company=item.get("company", ""),
                        location=location,
                        description=item.get("snippet", ""),
                        url=f"{_BASE}/viewjob?jk={jk}",
                        source=self.name,
                        posted_date=item.get("pubDate", ""),
                        salary=item.get("salarySnippet", {}).get("text", "") if isinstance(item.get("salarySnippet"), dict) else "",
                        job_type="full-time",
                    ))
                return
            except (json.JSONDecodeError, KeyError):
                pass

        # Fallback: basic regex for job keys
        jks = re.findall(r'"jk"\s*:\s*"([a-f0-9]+)"', html)
        titles = re.findall(r'"title"\s*:\s*"([^"]+)"', html)
        companies = re.findall(r'"company"\s*:\s*"([^"]+)"', html)

        for i, jk in enumerate(jks):
            if jk in seen_ids:
                continue
            seen_ids.add(jk)
            jobs.append(Job(
                title=titles[i] if i < len(titles) else "",
                company=companies[i] if i < len(companies) else "",
                location="Philippines",
                description="",
                url=f"{_BASE}/viewjob?jk={jk}",
                source=self.name,
                posted_date="",
                salary="",
                job_type="full-time",
            ))
