from __future__ import annotations

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateProfile":
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
