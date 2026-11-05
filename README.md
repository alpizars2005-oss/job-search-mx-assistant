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

The launcher detects Python, creates or repairs `.venv`, installs the project, validates Tkinter and SQLite, runs diagnostics, and opens the desktop interface. Startup failures are written to `jobsearch-startup.log`.

The same launcher can be run from PowerShell:

```powershell
.\START_WINDOWS.bat
```

There is no need to run a separate installer, activate the virtual environment, or change PowerShell's execution policy. The legacy `INSTALL_WINDOWS.bat` redirects to the same launcher.

> Requirement: Python 3.10 or newer. Keep **Add Python to PATH** and the **Tcl/Tk** component enabled when installing Python on Windows.

### Linux: one-command launcher

Download or clone the repository, open a terminal in its folder, and run:

```bash
bash START_LINUX.sh
```

This works even when an extracted ZIP does not preserve executable permissions. With a Git clone, direct execution can also be enabled:

```bash
chmod +x START_LINUX.sh
./START_LINUX.sh
```

The launcher:

- detects `python3` or `python` version 3.10 or newer;
- creates or repairs `.venv`;
- installs the local package when required;
- validates Tkinter, SQLite, and the user workspace;
- checks for an X11 or Wayland desktop session;
- opens the GUI and writes failures to `jobsearch-startup.log`.

When a system package is missing, it prints the appropriate installation command for Ubuntu/Debian/Mint, Fedora, Arch/Manjaro, or openSUSE. For example:

```bash
sudo apt update && sudo apt install python3 python3-venv python3-tk
```

Legacy Linux helpers now reuse the same startup process:

```bash
./scripts/install.sh
./scripts/run-gui.sh
```

### Advanced diagnostics

Windows:

```powershell
notepad .\jobsearch-startup.log
.\DEBUG_WINDOWS.bat
```

Linux:

```bash
cat jobsearch-startup.log
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

## Public job discovery (opt-in)

```bash
jobsearch discover
jobsearch discover --config examples/sources.example.json
```

Greenhouse, Lever and Ashby readers are disabled by default, including in the
example. Copy the source config outside the repository, review the board's terms,
and explicitly enable the boards you want to query. Discovery returns JSON with
field provenance, unknown eligibility and per-board partial/error reports. It
does not load profiles or write SQLite unless `--save` is requested, and never
submits applications. See the
[configuration and safety guide (Spanish)](docs/JOB_SOURCES.md). Existing profiles
remain JSON, and the desktop workflow is unchanged.

## Persistencia y matching explicable — Fase 3

`jobsearch discover --config /ruta/externa/sources.json --save` guarda las vacantes
normalizadas y evaluaciones versionadas. `jobsearch vacancies list` y
`jobsearch vacancies evaluate 1 --json` trabajan con los datos locales sin red.
SQLite migra de esquema 1 a 2 con backup previo y conserva todos los históricos.
Consulta [operación, perfil y rollback](docs/SQLITE_MATCHING.md).

## CV y candidaturas locales — Fase 4

`jobsearch resumes import /ruta/privada/master.json` incorpora un maestro bilingüe
con evidencia/atestación. `resumes tailor` genera TXT/DOCX sin inventar hechos;
`candidacies create/review/approve/simulate` enlaza empresa, vacante y versión/SHA
exacta mediante una autorización local de un uso. No hay envío externo y applied
continúa siendo seguimiento manual. SQLite esquema 3 preserva los históricos y
revoca permisos activos al recuperar backups. Ver
[operación y límites](docs/RESUMES_CANDIDACIES.md).

## Fit score

New evaluations check eligibility before compatibility and return one of the six
classifications documented in [AGENTS.md](AGENTS.md). Unknown essential facts
produce `insufficient_information`; a confirmed exclusion produces `ineligible`
regardless of the score. Remote work or a Mexico location alone does not confirm
that the employer can hire someone based in Mexico. Historical results keep their
original algorithm and labels. Known compatibility signals include:

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

## Automatización y monitoreo — Fase 5

`jobsearch automation run --config /private/sources.json --budget-seconds 120`
consulta fuentes habilitadas una vez, guarda/evalúa con historial y produce JSON
redactado. `automation health`, `runs` y `show ID` permiten diagnosticar sin leer
CV completos. Mutex OS, presupuesto y estados HTTP persistentes permiten reanudar.
No se crean ni envían candidaturas automáticamente. Telegram está retirado; Claude queda preparado/desactivado, sin revisión real ejecutada.
Ver [comandos, recuperación y límites](docs/AUTOMATION_MONITORING.md). Sin despliegue.

## Hardening de Fase 6 (pendiente de integración)

Matching `matching_v4`, controles privados POSIX, interrupciones sin penalizar fuentes,
Retry-After durable y suspensión manual, health con estado activo y esquema SQLite 5.
Telegram eliminado; datos históricos protegidos contra nuevas escrituras. No envíos.
La matriz CI incorpora Python 3.11 junto a 3.10/3.12/3.13 en Windows y Ubuntu.
Ver [operación y recuperación](docs/AUTOMATION_MONITORING.md). PizzaLab sigue pendiente.

## Preparación de operación y reportes (PR dependiente, sin despliegue)

```bash
jobsearch automation run --config /privado/sources.json --budget-seconds 600
jobsearch reports generate --config /privado/sources.json
jobsearch reports show 2026-11-04 --summary
jobsearch storage backup --output /privado/backups/FECHA-ID --config /privado/sources.json
jobsearch storage verify-backup /privado/backups/FECHA-ID
jobsearch storage inventory --retention-days 90 --keep-backups 7
```

Reportes diarios privados 14:00 America/Mexico_City, recuperables e idempotentes.
Backups completos SQLite+CV+config, restore a destino nuevo y retención sin borrado.
Instalación offline fijada y systemd preparados, sin activar servicios. GUI mantiene
exclusión sobre el mismo home mientras está abierta: cerrarla antes de backup/run.
Work no tiene entrega configurada/verificada; cero envíos de candidaturas confirmados.
Ver [producción/checklist](docs/DEPLOYMENT.md), [reportes](docs/DAILY_REPORTS.md) y
[recuperación](docs/STORAGE_RECOVERY.md). No se modificó PizzaLab.
