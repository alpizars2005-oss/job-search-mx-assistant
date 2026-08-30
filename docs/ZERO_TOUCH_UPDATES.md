# Zero-touch source updates

Date: 2026-08-30

## Goal

Keep the one-click Windows and Linux launchers current automatically when this application is run from its normal Git checkout. The launcher should fetch a newer `main` before opening the GUI, without ever overwriting local work.

## Safety rules

- Update only a real Git checkout on branch `main`.
- Require the configured `origin` to resolve to `alpizars2005-oss/job-search-mx-assistant` on GitHub.
- Refuse to update a dirty worktree or a checkout with local commits/divergence.
- Fetch only `origin main` and advance only with `git merge --ff-only`.
- Never use `reset --hard`, force checkout, stash, clean, or delete user files.
- Network/Git failures are non-fatal: log the reason and continue opening the installed local version.
- CI/detached-head/feature-branch checkouts are left untouched.

## Implementation

1. Add a standard-library-only `scripts/auto_update.py` helper with bounded Git subprocess calls and explicit repository/branch/cleanliness checks.
2. Call it from both one-click launchers after a usable Python environment exists and before application diagnostics/open.
3. Add unit tests for repository URL validation and the safe fast-forward decision flow.
4. Keep the existing CI launcher smoke tests; PR CI naturally exercises the safe skip path because Actions checks out a detached/temporary revision.

## Scope

This is intentionally a source-checkout updater. A packaged standalone build would need a signed or checksum-pinned public release feed; no credentials or private tokens are embedded in this project.