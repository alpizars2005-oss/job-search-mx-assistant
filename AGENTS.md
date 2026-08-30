# Agent development guide

This project handles user profile and job-posting data. Favor privacy, deterministic scoring, explainability, and minimal dependencies.

## Workflow

1. Read `PLAN.md`, `README.md`, `SECURITY.md`, `docs/ARCHITECTURE.md`, privacy docs, CI, and affected prompts before changes.
2. Prefer symbol/reference-aware navigation where available for refactors.
3. Verify third-party APIs and libraries against current official documentation before implementation; current-doc retrieval tools may assist, but official docs remain authoritative.
4. Preserve bilingual behavior and keep generated recommendations explainable from source inputs.
5. Validate imported job text/profile data and avoid logging personal data unnecessarily.
6. Add or update focused tests for parsing, ranking/scoring, and prompt/template changes, then run existing CI.
7. Browser automation should only be added for a real web workflow that cannot be covered by unit/integration tests.

## Review roles

For meaningful changes, perform separate implementation, test, privacy/security, and prompt-quality reviews.

## Completion gate

Do not complete a change until relevant tests pass and user-visible configuration or behavior is documented. Never weaken validation or privacy safeguards to simplify implementation.
