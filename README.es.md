# Job Search Assistant

Asistente bilingüe y privado para buscar trabajo en **Windows y Linux**. Permite evaluar la compatibilidad de una vacante, registrar aplicaciones, generar búsquedas, exportar datos y mantener un flujo de postulación consistente sin exigir una API de pago.

## Funciones principales

- Interfaz en español e inglés.
- Programa de escritorio y terminal con el mismo núcleo.
- Base local SQLite.
- Evaluación configurable según el perfil de cada usuario.
- Restricción de remoto, ubicación y nivel de experiencia.
- Detección de riesgos como pagos anticipados o vacantes sin sueldo base.
- Exportación a CSV y JSON.
- Sin postulaciones masivas automáticas ni scraping con sesión iniciada.
- Compatible con Windows y Linux.

## Inicio rápido

### Windows: un solo archivo

1. Descarga o clona el repositorio.
2. Extrae completamente el ZIP si lo descargaste como archivo comprimido.
3. Haz doble clic en **`START_WINDOWS.bat`**.

El iniciador detecta Python, crea o repara `.venv`, instala el programa, comprueba Tkinter y SQLite, ejecuta el diagnóstico y abre la interfaz. Si algo falla, conserva el reporte en `jobsearch-startup.log`.

También puede iniciarse desde PowerShell con una sola línea:

```powershell
.\START_WINDOWS.bat
```

No es necesario ejecutar previamente `INSTALL_WINDOWS.bat`, activar el entorno virtual ni cambiar la política de ejecución de PowerShell.

> Requisito: Python 3.10 o superior. Durante la instalación oficial de Python en Windows, activa **Add Python to PATH** y conserva el componente **Tcl/Tk**.

### Linux: un solo comando

Descarga o clona el repositorio, abre una terminal en su carpeta y ejecuta:

```bash
bash START_LINUX.sh
```

Ese comando funciona incluso cuando un ZIP no conserva permisos de ejecución. En una clonación también puedes habilitar el doble clic o la ejecución directa:

```bash
chmod +x START_LINUX.sh
./START_LINUX.sh
```

El iniciador:

- detecta `python3` o `python` con versión 3.10 o superior;
- crea o reconstruye `.venv` cuando sea necesario;
- instala el proyecto la primera vez;
- comprueba Tkinter, SQLite y la configuración;
- detecta si existe una sesión gráfica X11 o Wayland;
- abre la interfaz y guarda los errores en `jobsearch-startup.log`.

Si faltan paquetes del sistema, muestra el comando correcto para Ubuntu/Debian/Mint, Fedora, Arch/Manjaro u openSUSE. Por ejemplo, en Ubuntu o Linux Mint:

```bash
sudo apt update && sudo apt install python3 python3-venv python3-tk
```

### Diagnóstico avanzado

Windows:

```powershell
notepad .\jobsearch-startup.log
```

Linux:

```bash
cat jobsearch-startup.log
```

## Instalación manual opcional

### Windows

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m jobsearch_assistant init --language es
.\.venv\Scripts\python.exe -m jobsearch_assistant doctor
.\.venv\Scripts\python.exe -m jobsearch_assistant gui
```

### Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m jobsearch_assistant init --language es
.venv/bin/python -m jobsearch_assistant doctor
.venv/bin/python -m jobsearch_assistant gui
```

## Descubrimiento de vacantes públicas

La terminal incluye lectores opt-in de Greenhouse, Lever y Ashby:

```bash
jobsearch discover
jobsearch discover --config examples/sources.example.json
```

Sin configuración explícitamente habilitada no se hace ninguna solicitud.
Para activar un tablero, copia el ejemplo fuera del repositorio, revisa sus
condiciones y cambia solo su `enabled` a `true`. La salida JSON incluye
procedencia, campos desconocidos y reportes de error/resultados parciales.
No se presupone elegibilidad desde México. Sin `--save` no se leen perfiles ni
se guardan resultados en SQLite.
Consulta [configuración y límites](docs/JOB_SOURCES.md). Los perfiles siguen
usando JSON y la GUI conserva su flujo actual.

## Persistencia y matching explicable (Fase 3)

```bash
jobsearch discover --config /ruta/externa/sources.json --save
jobsearch vacancies list
jobsearch vacancies evaluate 1 --json
jobsearch analyze examples/job-posting.txt --language es
```

Las vacantes normalizadas se deduplican por proveedor, tablero e ID. Las
evaluaciones nuevas comprueban elegibilidad antes de clasificar la compatibilidad:
`high_priority`, `medium_priority`, `manual_review`, `rejected`, `ineligible` o
`insufficient_information`. Remoto o una ubicación México no prueban que el
empleador pueda contratar desde México; los datos esenciales ausentes se muestran
como desconocidos. El puntaje no es una probabilidad de contratación.

La Fase 3 introdujo esquema 2 con backup consistente previo y transacción;
Fase 4 lo amplía a 3. Los históricos conservan sus evaluaciones originales. Consulta
[migración, backup, rollback, perfil y límites](docs/SQLITE_MATCHING.md) antes de
actualizar una base importante. Guardar una vacante no crea ni envía una candidatura.

## CV y candidaturas locales

```bash
jobsearch resumes import /ruta/privada/master.json
jobsearch resumes tailor MASTER_ID --vacancy 1 --language es --format docx --claim FACT_ID
jobsearch candidacies create --vacancy 1 --resume VERSION_ID
jobsearch candidacies review 1
jobsearch candidacies approve 1 --digest DIGEST_REVISADO
jobsearch candidacies simulate AUTHORIZATION_ID
```

Maestros bilingües y documentos permanecen fuera del repositorio. Solo se componen
hechos respaldados/atestiguados; las versiones TXT/DOCX tienen huella SHA-256 y
trazabilidad. Aprobar vincula empresa, vacante, versión y contenido exactos; la
simulación consume una vez y devuelve `submitted=false`. No envía candidaturas.
SQLite migra ahora a esquema 3 con backup previo, preservando históricos.
Consulta [configuración, seguimiento, backup y checklist](docs/RESUMES_CANDIDACIES.md).
Las nuevas operaciones están en CLI; el tracker GUI anterior sigue disponible.

## Datos personales

El repositorio público no incluye el perfil de ninguna persona. Los datos se guardan en una carpeta local del usuario:

- Windows: `%APPDATA%\JobSearchAssistant`
- Linux: `~/.local/share/job-search-assistant`

También puedes definir `JOB_SEARCH_ASSISTANT_HOME` para escoger otra carpeta.

## Uso responsable

El programa no envía solicitudes automáticamente, no evita CAPTCHAs y no utiliza sesiones privadas de portales de empleo. Cada persona debe revisar y aprobar su postulación.

## Documentación

- [Guía en español](docs/USER_GUIDE.es.md)
- [Arquitectura](docs/ARCHITECTURE.md)
- [Privacidad](docs/PRIVACY.md)
- [Roadmap](docs/ROADMAP.md)

## Licencia

MIT. Consulta [LICENSE](LICENSE).

## Automatización y monitoreo — Fase 5

```bash
jobsearch automation run --config /ruta/privada/sources.json --budget-seconds 120
jobsearch automation health
jobsearch automation runs
jobsearch automation show ID_DE_EJECUCION
```

Ejecución única con bloqueo OS, presupuesto, cooldowns persistentes, matching e
historial. No crea/aprueba ni envía candidaturas. Telegram está retirado; no se necesitan credenciales ni se crean avisos. Claude oficial queda preparado, sin invocación real.
Consulta [operación, backup, privacidad y checklist](docs/AUTOMATION_MONITORING.md).
No hay scheduler residente ni despliegue en PizzaLab.

## Hardening de Fase 6 (pendiente de integración)

Matching `matching_v7`, controles privados POSIX, interrupciones sin penalizar fuentes,
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
