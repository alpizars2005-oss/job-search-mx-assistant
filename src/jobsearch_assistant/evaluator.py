from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .models import CandidateProfile, EvaluationResult, JobPosting

SENIOR_TERMS = ("senior", "sr.", "sr ", "lead", "principal", "manager", "director")
JUNIOR_TERMS = (
    "junior",
    "jr.",
    "entry level",
    "entry-level",
    "trainee",
    "intern",
    "internship",
    "associate",
    "sin experiencia",
    "practicante",
)
REMOTE_TERMS = ("remote", "remoto", "home office", "work from home", "anywhere")
ENGLISH_TERMS = ("english", "ingles", "inglés", "bilingual", "bilingue", "bilingüe")
SUSPICIOUS_TERMS = (
    "wire transfer",
    "gift card",
    "crypto payment",
    "telegram interview",
    "whatsapp interview only",
    "deposit to start",
    "deposito para iniciar",
    "compra tu equipo con nosotros",
)
COMMON_TECH_SKILLS = (
    "python",
    "javascript",
    "typescript",
    "java",
    "c#",
    "sql",
    "linux",
    "windows",
    "git",
    "github",
    "aws",
    "azure",
    "gcp",
    "docker",
    "kubernetes",
    "networking",
    "active directory",
    "ticketing",
    "jira",
    "selenium",
    "postman",
    "cybersecurity",
    "siem",
    "soc",
    "customer support",
    "technical support",
    "troubleshooting",
)


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_accents).strip()


def contains_phrase(text: str, phrase: str) -> bool:
    normalized_text = normalize(text)
    normalized_phrase = normalize(phrase)
    if not normalized_phrase:
        return False
    pattern = rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)"
    return re.search(pattern, normalized_text) is not None


def matching_phrases(text: str, phrases: Iterable[str]) -> list[str]:
    return sorted({phrase for phrase in phrases if contains_phrase(text, phrase)}, key=str.casefold)


def _skill_terms(profile: CandidateProfile, skill: str) -> list[str]:
    return [skill, *profile.skill_aliases.get(skill, [])]


def _extract_requested_skills(text: str) -> list[str]:
    return matching_phrases(text, COMMON_TECH_SKILLS)


def evaluate_job(profile: CandidateProfile, job: JobPosting) -> EvaluationResult:
    text = " ".join([job.title, job.company, job.location, job.description])
    normalized = normalize(text)
    score = 20
    reasons: list[str] = []
    positive: list[str] = []
    risks: list[str] = []

    matched_skills: list[str] = []
    for skill in profile.skills:
        if any(contains_phrase(text, term) for term in _skill_terms(profile, skill)):
            matched_skills.append(skill)

    requested_skills = _extract_requested_skills(text)
    missing_skills = [
        skill
        for skill in requested_skills
        if not any(
            contains_phrase(skill, term)
            for owned in profile.skills
            for term in _skill_terms(profile, owned)
        )
    ]

    if profile.skills:
        skill_ratio = len(matched_skills) / len(profile.skills)
        skill_points = min(35, round(skill_ratio * 35))
        score += skill_points
        reasons.append(f"skills:{len(matched_skills)}/{len(profile.skills)}")
    if matched_skills:
        positive.append("skill_match")

    role_signals = matching_phrases(text, profile.target_roles)
    if role_signals:
        score += min(18, 8 + 5 * len(role_signals))
        positive.append("target_role")
    else:
        reasons.append("no_target_role_signal")

    junior_signals = matching_phrases(text, JUNIOR_TERMS)
    senior_signals = matching_phrases(text, SENIOR_TERMS)
    if junior_signals:
        score += 10
        positive.append("junior_friendly")
    if senior_signals:
        score -= 20
        risks.append("senior_level")

    years = [int(value) for value in re.findall(r"\b(\d{1,2})\+?\s*(?:years?|anos|años)\b", normalized)]
    if years and max(years) >= 5:
        score -= 15
        risks.append(f"experience_requirement_{max(years)}_years")
    elif years and max(years) <= 2:
        score += 5
        positive.append("experience_requirement_accessible")

    remote_signals = matching_phrases(text, REMOTE_TERMS)
    if profile.remote_only:
        if remote_signals:
            score += 10
            positive.append("remote_match")
        elif job.location:
            score -= 18
            risks.append("remote_not_confirmed")

    location_signals = matching_phrases(text, profile.preferred_locations)
    if location_signals:
        score += 5
        positive.append("location_match")

    english_signals = matching_phrases(text, ENGLISH_TERMS)
    profile_languages = normalize(" ".join(profile.languages))
    if english_signals and "english" in profile_languages:
        score += 7
        positive.append("language_match")

    for breaker in profile.deal_breakers:
        if contains_phrase(text, breaker):
            risks.append(f"deal_breaker:{breaker}")
            score -= 25

    suspicious = matching_phrases(text, SUSPICIOUS_TERMS)
    if suspicious:
        risks.extend(f"suspicious:{item}" for item in suspicious)
        score -= 35

    score = max(0, min(100, score))
    if any(item.startswith("suspicious:") or item.startswith("deal_breaker:") for item in risks):
        recommendation = "review_risk"
    elif score >= 75:
        recommendation = "strong_fit"
    elif score >= 55:
        recommendation = "moderate_fit"
    elif score >= 35:
        recommendation = "stretch"
    else:
        recommendation = "low_fit"

    return EvaluationResult(
        score=score,
        recommendation=recommendation,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        role_signals=role_signals,
        positive_signals=sorted(set(positive)),
        risks=sorted(set(risks)),
        reasons=reasons,
    )
