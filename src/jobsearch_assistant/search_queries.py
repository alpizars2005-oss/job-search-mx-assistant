from __future__ import annotations

import unicodedata
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

REMOTE_INCLUDE_TERMS = (
    "100% remote",
    "fully remote",
    "remote position",
    "work from home",
    "home office",
    "remoto",
    "desde casa",
)

REMOTE_EXCLUDE_TERMS = (
    "presencial",
    "hibrido",
    "híbrido",
    "hybrid",
    "onsite",
    "on-site",
    "office based",
    "office-based",
    "trabajo en oficina",
)

REMOTE_LOCATION_ALIASES = {
    "remote",
    "remoto",
    "home office",
    "work from home",
    "desde casa",
    "worldwide",
    "anywhere",
}

DEFAULT_REMOTE_ELIGIBILITY = ("Mexico", "Latin America", "LATAM")


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char)).strip()


def _quoted_or(values: list[str] | tuple[str, ...]) -> str:
    return " OR ".join(f'"{value}"' for value in values)


def _remote_eligibility_locations(profile: CandidateProfile) -> list[str]:
    locations = [
        value.strip()
        for value in profile.preferred_locations
        if value.strip() and _normalize(value) not in REMOTE_LOCATION_ALIASES
    ]
    if not locations:
        locations = list(DEFAULT_REMOTE_ELIGIBILITY)

    unique: list[str] = []
    seen: set[str] = set()
    for location in locations:
        normalized = _normalize(location)
        if normalized not in seen:
            seen.add(normalized)
            unique.append(location)
    return unique[:4]


def _strict_remote_clause(profile: CandidateProfile) -> str:
    include_clause = f"({_quoted_or(REMOTE_INCLUDE_TERMS)})"
    locations = _remote_eligibility_locations(profile)
    location_clause = f"({_quoted_or(locations)})"
    exclusions = " ".join(f'-"{term}"' for term in REMOTE_EXCLUDE_TERMS)
    url_exclusions = "-inurl:presencial -inurl:hibrido -inurl:hybrid -inurl:onsite"
    return f"{include_clause} {location_clause} {exclusions} {url_exclusions}"


def build_search_queries(profile: CandidateProfile) -> list[str]:
    roles = profile.target_roles or ["technology"]
    queries: list[str] = []

    for role in roles:
        role_clause = f'"{role.strip()}"'
        if profile.remote_only:
            queries.append(f"{role_clause} {_strict_remote_clause(profile)}")
            continue

        locations = profile.preferred_locations or ["Mexico"]
        location_clause = f"({_quoted_or(locations[:4])})"
        queries.append(f"{role_clause} {location_clause}")

    return queries


def build_browser_urls(profile: CandidateProfile, portal: str = "linkedin") -> list[str]:
    domain = PORTAL_DOMAINS.get(portal, PORTAL_DOMAINS["linkedin"])
    return [
        f"https://www.google.com/search?q={quote_plus(f'site:{domain} {query}')}&tbs=qdr:m"
        for query in build_search_queries(profile)
    ]
