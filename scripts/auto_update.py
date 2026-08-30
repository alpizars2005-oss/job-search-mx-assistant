"""Conservative one-click updater for a normal Git source checkout.

This helper deliberately does nothing for packaged copies, feature branches,
detached CI checkouts, dirty worktrees, unexpected remotes, or divergent history.
It never modifies user work to make an update fit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_OWNER = "alpizars2005-oss"
EXPECTED_REPO = "job-search-mx-assistant"
TARGET_BRANCH = "main"
GIT_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class UpdateResult:
    status: str
    detail: str


def is_expected_origin(value: str) -> bool:
    """Accept only GitHub URLs that identify this exact repository."""
    raw = (value or "").strip()
    if not raw:
        return False

    # Common SSH scp syntax: git@github.com:owner/repo.git
    if raw.startswith("git@github.com:"):
        path = raw.split(":", 1)[1]
        parts = path.removesuffix(".git").strip("/").split("/")
        return parts == [EXPECTED_OWNER, EXPECTED_REPO]

    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if parsed.scheme not in {"https", "ssh", "git"}:
        return False
    if (parsed.hostname or "").casefold() != "github.com":
        return False
    parts = parsed.path.removesuffix(".git").strip("/").split("/")
    return parts == [EXPECTED_OWNER, EXPECTED_REPO]


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=check,
    )


def _stdout(*args: str) -> str:
    return run_git(*args).stdout.strip()


def update_checkout() -> UpdateResult:
    if not (ROOT / ".git").exists():
        return UpdateResult("skip", "not a Git checkout")

    try:
        if _stdout("rev-parse", "--is-inside-work-tree") != "true":
            return UpdateResult("skip", "not inside a Git worktree")

        branch = _stdout("rev-parse", "--abbrev-ref", "HEAD")
        if branch != TARGET_BRANCH:
            return UpdateResult("skip", f"branch is {branch!r}, not {TARGET_BRANCH!r}")

        origin = _stdout("remote", "get-url", "origin")
        if not is_expected_origin(origin):
            return UpdateResult("skip", "origin does not match the official project repository")

        if _stdout("status", "--porcelain"):
            return UpdateResult("skip", "local changes are present")

        # Fetch exactly the maintained branch from the already validated origin.
        run_git("fetch", "--quiet", "origin", TARGET_BRANCH)

        # A fetch cannot make a clean worktree dirty, but checking again makes the
        # invariant explicit before any ref-moving operation.
        if _stdout("status", "--porcelain"):
            return UpdateResult("skip", "worktree changed during update check")

        local_sha = _stdout("rev-parse", "HEAD")
        remote_sha = _stdout("rev-parse", f"origin/{TARGET_BRANCH}")
        if local_sha == remote_sha:
            return UpdateResult("current", local_sha)

        ancestor = run_git(
            "merge-base",
            "--is-ancestor",
            local_sha,
            remote_sha,
            check=False,
        )
        if ancestor.returncode != 0:
            return UpdateResult("skip", "local history diverged or contains unpublished commits")

        run_git("merge", "--ff-only", "--quiet", f"origin/{TARGET_BRANCH}")
        final_sha = _stdout("rev-parse", "HEAD")
        if final_sha != remote_sha:
            return UpdateResult("skip", "fast-forward did not reach the fetched revision")
        return UpdateResult("updated", f"{local_sha[:12]} -> {remote_sha[:12]}")
    except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        return UpdateResult("skip", f"update unavailable: {exc}")


def main() -> int:
    result = update_checkout()
    print(f"[auto-update] {result.status}: {result.detail}")
    # Updates are best-effort. A network/Git problem must not prevent the local
    # application from opening.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
