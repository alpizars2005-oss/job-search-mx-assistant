# Changelog

## Unreleased

- Validate imported profile structures and field types before use.
- Tolerate malformed settings, including invalid UTF-8, without rewriting the original file.
- Add 13 regression test methods for invalid inputs, valid-profile compatibility and file preservation.
- Explain the loader fallback and the evaluator's text-matching limitations in both user guides.

## 1.0.0 - 2026-07-22

- Added bilingual English/Spanish desktop interface.
- Added cross-platform CLI.
- Added profile-driven job-fit evaluator.
- Added local SQLite application tracker.
- Added CSV and JSON export.
- Added Windows and Linux install, run, and build scripts.
- Added privacy-first local data storage.
- Added automated tests and GitHub Actions CI.
