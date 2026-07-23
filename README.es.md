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

Eso es todo. El iniciador:

- detecta `py` o `python` automáticamente;
- comprueba que Python sea 3.10 o superior;
- crea o repara `.venv` cuando sea necesario;
- instala el proyecto localmente la primera vez;
- comprueba Tkinter, SQLite y la configuración;
- abre la interfaz gráfica;
- conserva un reporte en `jobsearch-startup.log` si algo falla.

También puede iniciarse desde PowerShell con una sola línea:

```powershell
.\START_WINDOWS.bat
```

No es necesario ejecutar previamente `INSTALL_WINDOWS.bat`, activar el entorno virtual ni cambiar la política de ejecución de PowerShell.

> Requisito: Python 3.10 o superior. Durante la instalación oficial de Python en Windows, activa **Add Python to PATH** y conserva el componente **Tcl/Tk**.

### Windows: diagnóstico avanzado

Si el iniciador no logra abrir la aplicación, revisa el reporte con:

```powershell
notepad .\jobsearch-startup.log
```

También se conserva `DEBUG_WINDOWS.bat` para diagnósticos manuales avanzados.

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
