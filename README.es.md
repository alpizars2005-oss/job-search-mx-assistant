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

### Windows: opción sencilla

1. Descarga o clona el repositorio.
2. Extrae el ZIP completo si lo descargaste como archivo comprimido.
3. Ejecuta `INSTALL_WINDOWS.bat` una sola vez.
4. Después, abre la aplicación con `START_WINDOWS.bat`.

Estos iniciadores no dependen de la política de ejecución de PowerShell y detectan automáticamente si Windows utiliza `py` o `python`.

### Windows: instalación manual

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m jobsearch_assistant init --language es
.\.venv\Scripts\python.exe -m jobsearch_assistant doctor
.\.venv\Scripts\python.exe -m jobsearch_assistant gui
```

Si `py` no existe, sustituye el primer comando por:

```powershell
python -m venv .venv
```

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
jobsearch init --language es
jobsearch-gui
```

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
