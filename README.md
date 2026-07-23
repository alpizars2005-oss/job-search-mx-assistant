# Job Search Assistant

A privacy-first, bilingual job-search workspace for **Windows and Linux**. It helps users evaluate job fit, track applications, generate safe search queries, export their data, and prepare a consistent application workflow without requiring a paid API.

> **Repository description:** Privacy-first bilingual job-search assistant for Windows and Linux: analyze job fit, track applications, export data, and prepare tailored application workflows.

[Leer en español](README.es.md)

## Why this project exists

Job searching is repetitive. Candidates repeatedly compare the same experience against different requirements, lose track of applications, and accidentally maintain several inconsistent versions of their profile. This project turns that work into a repeatable local workflow.

The application is built from scratch and is inspired by the workflow concept of AI-assisted job-search workspaces. It does not copy the original project's implementation.

## Highlights

- **English and Spanish UI** with persistent language settings.
- **Windows and Linux support** using Python's standard library.
- **Desktop GUI and CLI** powered by the same core.
- **Local SQLite tracker** with no cloud account required.
- **Profile-driven fit scoring**, not a hard-coded score for one person.
- **Remote-only and location constraints**.
- **Risk detection** for commission-only roles, upfront payments, and suspicious wording.
- **CSV and JSON exports**.
- **No automatic mass applications** and no login/session scraping.
- **Optional bilingual AI prompt library** for evaluation, resume tailoring, cover letters, and interviews.
- **AI-ready architecture** without making an API mandatory.
- **Automated tests and GitHub Actions** for Windows and Ubuntu.

## Quick start

### Windows: one-click launcher

1. Download or clone the repository.
2. Fully extract the ZIP if you downloaded an archive.
3. Double-click **`START_WINDOWS.bat`**.

The launcher automatically:

- detects `py` or `python`;
- requires Python 3.10 or newer;
- creates or repairs `.venv`;
- installs the local package when needed;
- validates Tkinter, SQLite, and the user workspace;
- opens the desktop interface;
- writes startup failures to `jobsearch-startup.log`.

The same launcher can be run from PowerShell with one command:

```powershell
.\START_WINDOWS.bat
```

There is no need to run a separate installer, activate the virtual environment, or change PowerShell's execution policy. The legacy `INSTALL_WINDOWS.bat` now redirects to the same one-click launcher.

> Requirement: Python 3.10 or newer. Keep **Add Python to PATH** and the **Tcl/Tk** component enabled when installing Python on Windows.

For advanced diagnostics:

```powershell
notepad .\jobsearch-startup.log
.\DEBUG_WINDOWS.bat
```

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
jobsearch init
jobsearch-gui
```

Or run the installer:

```bash
chmod +x scripts/*.sh
./scripts/install.sh
./scripts/run-gui.sh
```

Portable mode:

```bash
./scripts/run-cli.sh doctor
./scripts/run-gui.sh
```

## CLI examples

Initialize the local workspace:

```bash
jobsearch init --language es
```

Analyze a posting saved as text:

```bash
jobsearch analyze examples/job-posting.txt \
  --title "Technical Support Specialist" \
  --company "Example Company" \
  --location "Remote - Mexico"
```

Analyze and save it to the tracker:

```bash
jobsearch analyze examples/job-posting.txt --save
```

List applications:

```bash
jobsearch applications list
jobsearch applications list --status interview
```

Update an application:

```bash
jobsearch applications update 1 --status applied
```

Export data:

```bash
jobsearch export --format csv --output applications.csv
jobsearch export --format json --output applications.json
```

Validate the installation:

```bash
jobsearch doctor
```

## Fit score

The evaluator combines:

1. Candidate skill matches.
2. Target-role signals.
3. Seniority compatibility.
4. Language requirements.
5. Remote and location constraints.
6. Explicit deal-breakers and suspicious wording.

The score is an aid, not a hiring decision. It intentionally shows matched evidence, missing signals, and risks instead of presenting a mysterious AI number.

## Privacy model

The public repository contains no personal profile. User data is stored outside the repository:

- Windows: `%APPDATA%\JobSearchAssistant`
- Linux: `~/.local/share/job-search-assistant`
- Override: `JOB_SEARCH_ASSISTANT_HOME=/custom/path`

The generated database and profile are never committed unless the user deliberately copies them into the repository.

## Project structure

```text
src/jobsearch_assistant/   Application source
scripts/                   Windows and Linux helpers
examples/                  Generic sample profile and posting
prompts/                   Optional English/Spanish AI workflows
docs/                      Architecture, privacy, and user guides
tests/                     Automated tests
.github/                   CI and contribution templates
```

## Build a standalone executable

PyInstaller is optional:

```powershell
.\scripts\build.ps1
```

```bash
./scripts/build.sh
```

The generated executable appears under `dist/`. Linux executables must be built on Linux; Windows executables must be built on Windows.

## Responsible use

This project does not automatically submit applications, bypass CAPTCHAs, reuse authenticated browser sessions, or scrape private pages. Users should review every application and follow each platform's terms.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md). Planned additions include optional local LLM support, browser-assisted import, richer analytics, and resume-template plugins.

## License

MIT. See [LICENSE](LICENSE).
