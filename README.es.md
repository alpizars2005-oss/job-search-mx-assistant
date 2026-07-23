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
