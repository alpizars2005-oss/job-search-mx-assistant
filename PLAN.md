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

---

## Audit follow-up — CSV export safety (2026-08-30)

### Finding

Job titles, companies, locations, URLs, skills, risks and notes can originate from job postings or user input. CSV files are commonly opened in spreadsheet applications, where cells beginning with `=`, `+`, `-`, or `@` can be interpreted as formulas. The current exporter writes those strings verbatim.

### Atomic commit plan

1. Neutralize formula-like text only in CSV output while keeping JSON exports and stored application data unchanged.
2. Add focused tests for formula prefixes, normal text and numeric values.
3. Run the existing test suite/CI.

### Risk / rollback

Low. This changes only presentation in CSV exports. A leading apostrophe is added to potentially executable spreadsheet text; source records, scoring and JSON output remain untouched.

---

## Audit follow-up — profile and settings loading (2026-09-25)

### Reproduced problem

At `f972bb013b32c3e1802ba6b1ce05ba8b9331281b`, valid JSON is not necessarily a valid profile or settings object. A profile containing `[]` raises `AttributeError`; settings containing `null` do the same; a language value containing a list raises `TypeError`. Profile fields also accept incompatible types, such as a string instead of a skills list.

The existing configuration test covers the normal workspace path, not these inputs. Five existing configuration/evaluator tests passed in the local source snapshot before changes. The snapshot files were checked against their Git blob hashes; this is not a full local clone or a Windows GUI test.

### Atomic commit plan

1. Record the reproduced defects and compatibility boundary before changing code.
2. Validate the JSON shape at `CandidateProfile.from_dict`, guard settings loading, and add regression tests using temporary workspaces. Preserve valid profiles, defaults, unknown-field tolerance, scoring and stored files.
3. Document the behavior in both user-guide languages and record actual test results. Run the existing complete CI matrix on the review branch through a pull request.

### Boundaries

No dependencies, database changes, launcher changes, scoring changes, or user-data migrations. Invalid stored files must remain untouched so they can be inspected and recovered. Validation messages name the field, not its personal contents.

The separate finding that negated remote-work wording can produce a positive remote signal is not silently folded into this loading fix.

### Risk and rollback

Low for profiles following the documented JSON types. Malformed field types previously accepted by accident will be rejected on import; stored malformed profiles retain the existing in-memory default fallback. Revert the focused implementation commit to restore the previous loader; there is no data migration to reverse.
