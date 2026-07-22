# Privacy

Job Search Assistant stores profiles, job descriptions, notes, and application history locally. No telemetry is included.

## Local paths

- Windows: `%APPDATA%\JobSearchAssistant`
- Linux: `$XDG_DATA_HOME/job-search-assistant` or `~/.local/share/job-search-assistant`

Set `JOB_SEARCH_ASSISTANT_HOME` to use another directory.

## Recommendations

- Do not commit the local profile or database.
- Remove private details before sharing exports.
- Store API keys in environment variables if optional providers are added later.
- Review every generated document before submitting it.
