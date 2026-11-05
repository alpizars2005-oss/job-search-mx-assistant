from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any

from .models import CandidateProfile
from .private_storage import PrivateStorageError, private_path, private_directory, protect_private_file, read_private, write_private

APP_NAME = "JobSearchAssistant"


def data_home() -> Path:
    override = os.getenv("JOB_SEARCH_ASSISTANT_HOME")
    if override:
        # Validate the supplied spelling before canonicalizing Windows 8.3 names;
        # otherwise resolve() could conceal a supplied symlink or junction.
        supplied = private_path(Path(override).expanduser())
        return private_path(supplied.resolve())

    if platform.system() == "Windows":
        base = Path(os.getenv("APPDATA", Path.home()))
        return private_path(base / APP_NAME)

    xdg = os.getenv("XDG_DATA_HOME")
    if xdg:
        return private_path(Path(xdg).expanduser() / "job-search-assistant")
    return private_path(Path.home() / ".local" / "share" / "job-search-assistant")


def settings_path() -> Path:
    return data_home() / "settings.json"


def profile_path() -> Path:
    return data_home() / "profile.json"


def database_path() -> Path:
    return data_home() / "applications.sqlite3"


def ensure_workspace(language: str = "es") -> Path:
    home = private_directory(data_home())
    if not os.path.lexists(settings_path()):
        save_settings({"language": language if language in {"en", "es"} else "es"})
    else:
        protect_private_file(settings_path())
    if not os.path.lexists(profile_path()):
        save_profile(default_profile())
    else:
        protect_private_file(profile_path())
    return home


def load_settings() -> dict[str, Any]:
    ensure_workspace()
    try:
        data = json.loads(read_private(settings_path(), None).decode('utf-8'))
    except PrivateStorageError:
        raise
    except (OSError, ValueError, UnicodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    language = data.get("language", "es")
    if not isinstance(language, str) or language not in {"en", "es"}:
        language = "es"
    return {"language": language}


def save_settings(settings: dict[str, Any]) -> None:
    private_directory(data_home())
    language = settings.get("language", "es")
    if language not in {"en", "es"}:
        raise ValueError("language must be 'en' or 'es'")
    write_private(settings_path(), json.dumps({"language": language}, ensure_ascii=False, indent=2).encode('utf-8'))


def load_profile() -> CandidateProfile:
    ensure_workspace()
    try:
        raw = json.loads(read_private(profile_path(), None).decode('utf-8'))
        return CandidateProfile.from_dict(raw)
    except PrivateStorageError:
        raise
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default_profile()


def save_profile(profile: CandidateProfile) -> None:
    private_directory(data_home())
    write_private(profile_path(), json.dumps(profile.to_dict(), ensure_ascii=False, indent=2).encode('utf-8'))


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
