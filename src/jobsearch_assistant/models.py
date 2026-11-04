from __future__ import annotations

import math

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


VALID_STATUSES = (
    "saved",
    "interested",
    "applied",
    "screening",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
)


@dataclass(slots=True)
class CandidateProfile:
    name: str = ""
    headline: str = ""
    location: str = ""
    languages: list[str] = field(default_factory=lambda: ["Spanish", "English"])
    skills: list[str] = field(default_factory=list)
    target_roles: list[str] = field(default_factory=list)
    preferred_locations: list[str] = field(default_factory=list)
    remote_only: bool = True
    accepted_seniority: list[str] = field(
        default_factory=lambda: ["intern", "trainee", "entry", "junior", "associate"]
    )
    deal_breakers: list[str] = field(
        default_factory=lambda: [
            "commission only",
            "solo comisiones",
            "upfront payment",
            "pago por adelantado",
            "pay for training",
            "pagar capacitacion",
        ]
    )
    skill_aliases: dict[str, list[str]] = field(default_factory=dict)

    residence_country: str | None = None
    work_authorized_countries: list[str] | None = None
    experience_years: float | None = None
    degree_completed: bool | None = None
    language_levels: dict[str, str] = field(default_factory=dict)
    conditions: dict[str, bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateProfile":
        # JSON syntax and dataclass annotations do not validate imported types.
        if not isinstance(data, dict):
            raise ValueError("profile must be a JSON object")

        for name in ("name", "headline", "location"):
            if name in data and not isinstance(data[name], str):
                raise ValueError(f"{name} must be a string")

        for name in (
            "languages", "skills", "target_roles", "preferred_locations",
            "accepted_seniority", "deal_breakers",
        ):
            if name in data:
                value = data[name]
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ValueError(f"{name} must be an array of strings")

        if "remote_only" in data and not isinstance(data["remote_only"], bool):
            raise ValueError("remote_only must be a boolean")

        if "skill_aliases" in data:
            aliases = data["skill_aliases"]
            if not isinstance(aliases, dict) or not all(
                isinstance(key, str)
                and isinstance(values, list)
                and all(isinstance(item, str) for item in values)
                for key, values in aliases.items()
            ):
                raise ValueError("skill_aliases must map strings to arrays of strings")

        def country(value):
            return isinstance(value, str) and len(value) == 2 and value.isascii() and value.isalpha() and value.isupper()

        if data.get("residence_country") is not None and not country(data["residence_country"]):
            raise ValueError("residence_country must be an uppercase country code or null")
        countries = data.get("work_authorized_countries")
        if countries is not None and (not isinstance(countries, list) or not all(country(c) for c in countries)):
            raise ValueError("work_authorized_countries must be an array of country codes or null")
        years = data.get("experience_years")
        if years is not None and (type(years) not in (int, float) or not 0 <= years <= 100 or not math.isfinite(years)):
            raise ValueError("experience_years must be a finite nonnegative number or null")
        if data.get("degree_completed") is not None and type(data["degree_completed"]) is not bool:
            raise ValueError("degree_completed must be a boolean or null")
        if "language_levels" in data:
            levels = data["language_levels"]
            accepted = {"A1", "A2", "B1", "B2", "C1", "C2", "native", "basic", "intermediate", "advanced", "fluent"}
            if not isinstance(levels, dict) or not all(
                isinstance(k, str) and bool(k.strip()) and isinstance(v, str) and v in accepted
                for k, v in levels.items()
            ):
                raise ValueError("language_levels must map languages to supported proficiency levels")
        if "conditions" in data:
            conditions = data["conditions"]
            if not isinstance(conditions, dict) or not all(
                isinstance(k, str) and bool(k.strip()) and (v is None or type(v) is bool)
                for k, v in conditions.items()
            ):
                raise ValueError("conditions must map condition names to booleans or null")

        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass(slots=True)
class JobPosting:
    title: str = "Untitled role"
    company: str = "Unknown company"
    location: str = ""
    url: str = ""
    description: str = ""


@dataclass(slots=True)
class EvaluationResult:
    score: int
    recommendation: str
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    role_signals: list[str] = field(default_factory=list)
    positive_signals: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    algorithm_version: str = "legacy_v1"
    requirements: list[dict[str, Any]] = field(default_factory=list)
    requirements_met: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    restrictions: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ApplicationRecord:
    id: int | None
    job: JobPosting
    evaluation: EvaluationResult
    status: str = "saved"
    notes: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
