# User Guide

1. Run `jobsearch init`.
2. Open `jobsearch-gui`.
3. Complete the Profile tab.
4. Paste a job description into Analyze.
5. Review the score, matched skills, missing skills, and risks.
6. Save promising roles.
7. Update application status and notes from the Applications tab or CLI.
8. Export CSV or JSON backups regularly.

Scores use text rules; they do not confirm eligibility or replace reading the posting. Negated wording such as `not remote` can still match the word `remote`. Check the work arrangement, location and mandatory requirements in the original posting before deciding.

## Import a profile

```bash
jobsearch profile import profile.json
```

The file must contain a JSON object. `name`, `headline` and `location` must be strings. Skills, languages, roles, locations, seniority levels and deal breakers must be arrays of strings. `remote_only` accepts `true` or `false`, not quoted strings; `skill_aliases` maps skill names to arrays of aliases.

Omitted fields keep their defaults and unknown fields are ignored. Invalid field types produce an import error without replacing the previous profile. The error names the field rather than repeating its personal contents.

## When a saved file cannot be loaded

Loading an invalid stored profile uses the default profile in memory. Invalid settings use Spanish. The loader leaves the original files untouched: this prevents an unexpected crash, but does not repair their contents or confirm that your preferences have been recovered.

Keep a copy of the original file before editing or saving the profile again. Check `profile.json` and `settings.json` in the data directory described in [Privacy](PRIVACY.md).
