from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any

from .models import CandidateProfile

APP_NAME = "JobSearchAssistant"


def data_home() -> Path:
    override = os.getenv("JOB_SEARCH_ASSISTANT_HOME")
    if override:
        return Path(override).expanduser().resolve()

    if platform.system() == "Windows":
        base = Path(os.getenv("APPDATA", Path.home()))
        return base / APP_NAME

    xdg = os.getenv("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "job-search-assistant"
    return Path.home() / ".local" / "share" / "job-search-assistant"


def settings_path() -> Path:
    return data_home() / "settings.json"


def profile_path() -> Path:
    return data_home() / "profile.json"


def database_path() -> Path:
    return data_home() / "applications.sqlite3"


def ensure_workspace(language: str = "es") -> Path:
    home = data_home()
    home.mkdir(parents=True, exist_ok=True)
    if not settings_path().exists():
        save_settings({"language": language if language in {"en", "es"} else "es"})
    if not profile_path().exists():
        save_profile(default_profile())
    return home


def load_settings() -> dict[str, Any]:
    ensure_workspace()
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    language = data.get("language", "es")
    if language not in {"en", "es"}:
        language = "es"
    return {"language": language}


def save_settings(settings: dict[str, Any]) -> None:
    data_home().mkdir(parents=True, exist_ok=True)
    language = settings.get("language", "es")
    if language not in {"en", "es"}:
        raise ValueError("language must be 'en' or 'es'")
    settings_path().write_text(
        json.dumps({"language": language}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_profile() -> CandidateProfile:
    ensure_workspace()
    try:
        raw = json.loads(profile_path().read_text(encoding="utf-8"))
        return CandidateProfile.from_dict(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default_profile()


def save_profile(profile: CandidateProfile) -> None:
    data_home().mkdir(parents=True, exist_ok=True)
    profile_path().write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def default_profile() -> CandidateProfile:
    return CandidateProfile(
        headline="Junior technology professional",
        skills=["customer support", "troubleshooting", "python", "linux", "git"],
        target_roles=[
            "technical support",
            "help desk",
            "junior developer",
            "qa tester",
            "cybersecurity analyst",
        ],
        preferred_locations=["remote", "mexico", "latam"],
        skill_aliases={
            "customer support": ["customer service", "atencion al cliente", "support"],
            "troubleshooting": ["diagnostics", "problem solving", "resolucion de problemas"],
            "python": ["python3", "scripting", "automation"],
            "linux": ["ubuntu", "bash", "terminal"],
            "git": ["github", "version control", "control de versiones"],
        },
    )
