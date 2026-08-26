# Repository Improvement Plan

Date: 2026-08-26

## Goal

Improve supply-chain security and maintainability of the existing privacy-first job-search application without changing scoring, application data, launcher behavior, or storage semantics.

## Audit findings

- The repository already has mature hygiene: bilingual docs, architecture/privacy docs, issue/PR templates, tests, launchers, examples, security policy, and CI on Windows/Linux.
- CI currently references GitHub Actions through moving major tags (`checkout@v4`, `setup-python@v5`).
- The current matrix is valuable and should be preserved rather than replaced with a heavier toolchain.

## Atomic commit plan

1. Document the repository audit.
2. Pin CI actions to verified immutable SHAs and keep minimum token permissions.
3. Add a lightweight source-quality smoke check only if it can run without new runtime dependencies.
4. Re-run/review CI and document follow-up work.

## Validation

- Preserve the Windows/Linux Python matrix and launcher smoke tests.
- Keep `contents: read` as the only workflow permission.
- Ensure `python -m jobsearch_assistant --help` still runs in CI.

## Risk / rollback

Very low. This audit pass is intentionally CI-focused because the application already has good project structure. Revert the workflow commit if CI behavior changes unexpectedly.
