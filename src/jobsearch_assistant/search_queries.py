from __future__ import annotations

from urllib.parse import quote_plus

from .models import CandidateProfile

PORTAL_DOMAINS = {
    "linkedin": "linkedin.com/jobs/view",
    "indeed": "indeed.com/viewjob",
    "computrabajo": "computrabajo.com",
    "occ": "occ.com.mx/empleos",
    "getonboard": "getonbrd.com/jobs",
    "wellfound": "wellfound.com/jobs",
    "weworkremotely": "weworkremotely.com/remote-jobs",
}


def build_search_queries(profile: CandidateProfile) -> list[str]:
    roles = profile.target_roles or ["technology"]
    locations = profile.preferred_locations or ["remote"]
    queries: list[str] = []
    for role in roles:
        location_clause = " OR ".join(f'"{location}"' for location in locations[:3])
        remote_clause = ' "remote"' if profile.remote_only else ""
        queries.append(f'"{role}" ({location_clause}){remote_clause}')
    return queries


def build_browser_urls(profile: CandidateProfile, portal: str = "linkedin") -> list[str]:
    domain = PORTAL_DOMAINS.get(portal, PORTAL_DOMAINS["linkedin"])
    return [
        f"https://www.google.com/search?q={quote_plus(f'site:{domain} {query}')}"
        for query in build_search_queries(profile)
    ]
