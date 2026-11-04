# Auditoría verificable de Fase 1

Consulta: 2026-11-04. Repositorio: `alpizars2005-oss/job-search-mx-assistant`.
Base inspeccionada: `54c7c9ee21fd88625386799782f40da8b6882a5d` (`main`).
Al inicio, checkout limpio en `work`; `git fetch origin main` confirmó la misma
base local/remota. Rama de entrega: `codex/phase-1-audit-plan`.

Esta entrega solo modifica reglas, documentación y ejemplos de planificación.
No se corrigieron defectos funcionales ni se añadieron conectores, loaders,
dependencias, servicios o pruebas al producto. Los experimentos usaron datos
sintéticos en directorios temporales externos, sin abrir archivos privados.

## Inventario y decisiones que se conservan

Se inspeccionaron los 66 archivos versionados de la base, incluidos código,
pruebas, prompts bilingües, launchers, empaquetado, documentos, plantillas y CI.
Historial local no superficial: 90 commits alcanzables y 100 blobs únicos.
Estructura principal:

```text
.github/                 CI, plantillas de PR e issues
src/jobsearch_assistant/  modelos, configuración, SQLite, evaluación, interfaces
scripts/                 instalación, ejecución, empaquetado y actualización
examples/                perfil JSON y vacante sintéticos
prompts/{en,es}/          ocho prompts para uso manual
tests/                   siete archivos de pruebas
docs/                    arquitectura, privacidad, guías y roadmap histórico
```

| Componente | Estado | Evidencia y límites |
| --- | --- | --- |
| Modelos y perfiles JSON | Funcional y verificado | Validación de tipos, defaults y recuperación probados; YAML aún no soportado |
| Rutas y ajustes locales | Funcional y verificado | `JOB_SEARCH_ASSISTANT_HOME`, idioma y preservación de archivos inválidos cubiertos |
| Tracker SQLite | Funcional y verificado para CRUD | Esquema 1, transacciones, WAL, cierre de conexiones, SQL parametrizado y estados; no hay migraciones incrementales |
| Deduplicación | Parcialmente implementada | CLI/GUI consultan `find_duplicate`; INSERT sin unicidad, reproducción más abajo |
| Evaluador actual | Funcional para reglas existentes; defectuoso como filtro de elegibilidad | Coincidencias/penalizaciones probadas; negaciones y requisitos excluyentes no resueltos |
| Exportadores | Funcional y verificado parcialmente | CSV/JSON implementados; dos pruebas pytest de neutralización CSV y recorrido CLI sintético; sin cobertura completa de serialización |
| CLI | Funcional y verificado parcialmente | Ayuda, doctor y recorrido sintético de tracker; no cobertura completa de errores CLI |
| GUI Tkinter | Existente, pero no verificado interactivamente | Código inspeccionado y compilado; importación Tk comprobada por launcher, sin abrir ventana |
| Idiomas inglés/español | Existente, pero no verificado visualmente | Diccionarios paralelos; CLI y recomendaciones todavía contienen textos/identificadores en inglés |
| Búsquedas por enlaces | Funcional y verificado | Consultas Google con dominio y parámetros codificados; no descarga LinkedIn/Indeed |
| Launchers Linux | Funcional y verificado en preparación | Sintaxis y `JOBSEARCH_PREPARE_ONLY=1`; sin validar GUI ni reinstalación desde cero |
| Launchers Windows/PowerShell | Existente, pero no verificado aquí | Inspección estática; ejecución requiere Windows |
| `scripts/install.sh` | Funcional como wrapper | Invoca preparación de `START_LINUX.sh`; `install.sh` en raíz no existe |
| `gui_smoke.py` | Ausente | No existe en el árbol; no se creó para esta auditoría |
| Actualizador Git | Funcional y verificado parcialmente | Seis pruebas sintéticas; `main` limpio/oficial y fast-forward, timeout 15 s; no se ejecutó una actualización real |
| Prompts bilingües | Parcialmente implementados | Plantillas manuales con restricciones de honestidad; no hay integración de modelos o generación de documentos |
| CI | Funcionalidad existente, cobertura parcial | Matriz 2 SO × 3 Python; SHA fijos y permisos mínimos; omite funciones pytest CSV |
| PyInstaller | Existente, pero no verificado | Extra opcional y scripts; no se generó un ejecutable |
| Conectores ATS y feeds | Ausente | Catálogo nuevo solo documental, deshabilitado |
| Matching excluyente y estados objetivo | Ausente | No existen `ineligible`/`insufficient_information` ni prioridades nuevas en runtime |
| Aprobación por CV y generación integrada | Ausente | Guardar/cambiar `applied` solo modifica seguimiento local |
| Telegram, scheduler, revisión Claude, PizzaLab | Ausente | Ningún servicio configurado o desplegado por esta fase |
| Normalización de texto | Duplicada parcialmente | `evaluator.normalize` y `search_queries._normalize`; los consumidores tienen diferencias, no fusionar sin pruebas |
| Helpers de instalación | Duplicados como entradas compatibles | Linux delega al launcher; PowerShell conserva instalación separada; no eliminar por formalidad |
| PLAN y roadmap anteriores | Obsoletos como plan de esta misión | Historial conservado por Git y referencia desde PLAN nuevo; `docs/ROADMAP.md` contiene ideas opcionales, no autorización |

Decisiones anteriores respetadas: biblioteca estándar en runtime, privacidad
local, CLI/GUI con núcleo compartido, defaults JSON, exportación CSV protegida,
validación de perfiles del PR #5, actualizador conservador y CI fijado por SHA.
No se encontró una base SQLite, CV, `.env` o clave privada versionada. Los únicos
ignorados observados inicialmente eran `.venv`, cachés y metadatos de instalación.
No se inspeccionó contenido de directorios privados externos al repositorio.

## Validaciones ejecutadas

Entorno: Linux x86_64, kernel 6.18.57, glibc 2.41, Python 3.12.14,
SQLite de la biblioteca estándar. `.venv` y paquete editable ya preparados por
Cloud; no se ejecutaron instaladores remotos ni scripts de los proyectos externos.
Herramientas existentes: pytest 9.2.0, Ruff 0.17.3, mypy 2.4.1, pip 25.0.1.
No se ejecutó mypy: no forma parte de CI y esta entrega no modifica tipos/código.

Desde la raíz del repositorio:

| Comando exacto | Resultado real | Límite |
| --- | --- | --- |
| `git fetch origin main` | Salida 0; remoto/base iguales | Comprobación del momento, no bloqueo frente a futuros cambios |
| `.venv/bin/python -m unittest discover -s tests -v` | 29 pruebas, OK | No descubre las dos funciones de `test_exporters.py` |
| `.venv/bin/python -m pytest -q` | 31 passed, 106 subtests passed | Suite local Linux/Python 3.12; no matriz remota implícita |
| `.venv/bin/python -m pip check` | No broken requirements found | Compatibilidad de dependencias; no es análisis de CVE |
| `.venv/bin/python -m compileall -q src scripts tests run_cli.py run_gui.py` | Salida 0, sin errores | Compilación, no ejecución de todos los caminos |
| `.venv/bin/python -m jobsearch_assistant --help` | Salida 0, nueve subcomandos | No abre la GUI ni verifica todos los subcomandos |
| `bash -n START_LINUX.sh scripts/install.sh scripts/run-cli.sh scripts/run-gui.sh scripts/build.sh` | Salida 0 | Sintaxis de Bash, no instalación/empaquetado |
| `.venv/bin/python -m ruff check src scripts tests run_cli.py run_gui.py --output-format concise` | Salida 1, 13 diagnósticos preexistentes | Configuración heredada del entorno, no gate de CI; no se alteró código para silenciarlos |

Ruff informó `I001`, `F401` (importación `sys` sin uso), `FLY002`, `PIE810`,
`UP037`, `TRY004` y `SIM117`. No son regresiones de esta entrega documental.

El diagnóstico y smoke Linux se ejecutaron con este comando aislado:

```bash
python3 - <<'PY'
import os, subprocess, tempfile
with tempfile.TemporaryDirectory(prefix='jobsearch-phase1-') as directory:
    env = dict(os.environ, JOB_SEARCH_ASSISTANT_HOME=directory,
               JOBSEARCH_PREPARE_ONLY='1', JOBSEARCH_NONINTERACTIVE='1')
    for args in [
        ['.venv/bin/python', '-m', 'jobsearch_assistant', 'doctor'],
        ['bash', 'START_LINUX.sh'],
    ]:
        result = subprocess.run(args, env=env, capture_output=True, text=True)
        print(args, result.returncode, result.stdout, result.stderr)
PY
```

Ambos procesos devolvieron 0. Doctor indicó `Status: OK`; launcher encontró la
instalación, importó Tkinter, ejecutó doctor y terminó con `Preparation completed
successfully`. Se eliminó únicamente `jobsearch-startup.log` creado por esta
prueba, cuya inexistencia inicial estaba comprobada. No se borraron datos previos.
Esto es preparación headless soportada por el launcher, **no una prueba gráfica
interactiva**, y no prueba instalación desde un equipo vacío.

Las validaciones YAML y controles finales están documentados al final de este
archivo tras su ejecución. La ejecución remota de CI se consulta por separado
en el PR; no se presume aprobada a partir de estas pruebas locales.

## Defectos reproducibles y causa

Prioridad alta para uso automático; no se corrigieron en esta fase.
Ejecutado con `.venv/bin/python` desde la raíz, sin red ni datos reales:

```bash
.venv/bin/python - <<'PY'
import sqlite3, tempfile
from pathlib import Path
from jobsearch_assistant.models import (
    CandidateProfile, JobPosting, ApplicationRecord, EvaluationResult,
)
from jobsearch_assistant.evaluator import evaluate_job
from jobsearch_assistant.database import ApplicationDatabase
profile = CandidateProfile(
    skills=['python'], target_roles=['junior developer'],
    preferred_locations=['mexico'], languages=['English'], remote_only=True,
)
for label, job in [
    ('negated_remote', JobPosting(
        title='Junior Developer', location='Mexico',
        description='Python English. This job is not remote. 1 year of experience.')),
    ('us_only', JobPosting(
        title='Junior Developer', location='Remote - United States only',
        description='Python English. Must reside in the United States. 1 year of experience.')),
    ('unknown', JobPosting()),
]:
    result = evaluate_job(profile, job)
    print(label, result.score, result.recommendation)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'synthetic.sqlite3'
    database = ApplicationDatabase(path)
    record = ApplicationRecord(
        id=None, job=JobPosting(title='Example', company='Synthetic'),
        evaluation=EvaluationResult(score=80, recommendation='strong_fit'),
    )
    database.add(record)
    database.add(record)
    print('duplicate_count', len(database.list()))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    ApplicationDatabase(path)
    with sqlite3.connect(path) as connection:
        print('schema_marker_after_reopen', connection.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
PY
```

Salida observada:

```text
negated_remote 100 strong_fit
us_only 100 strong_fit
unknown 20 low_fit
duplicate_count 2
schema_marker_after_reopen 1
```

- `evaluator.py:evaluate_job` busca palabras sin negación ni una etapa de
  elegibilidad. `remote` aporta puntos aunque esté negado; no se comprueba
  autorización de contratación en México ni restricciones de residencia.
  Una vacante vacía recibe `low_fit`, no un estado de información insuficiente.
  `accepted_seniority` se valida en el perfil pero no determina la evaluación.
- `database.py:add` acepta duplicados; la comprobación previa en CLI/GUI está
  separada del INSERT y el índice compañía/título no es único. El experimento
  demuestra ausencia de unicidad, no una carrera ejecutada con dos procesos.
- `database.py:initialize` ejecuta `INSERT OR REPLACE` del marcador de esquema
  sin leer la versión previa. El experimento cambia solo metadatos sintéticos;
  no afirma haber migrado un esquema real de versión 99.

Criterios de corrección y fases responsables en `PLAN.md`: elegibilidad y
clasificación antes del score, migraciones que rechacen versiones desconocidas,
unicidad transaccional y pruebas de reinicio/concurrencia en Fase 3.

## Revisión de seguridad y límites

Revisión manual de código, dependencias declaradas, comandos, permisos, prompts,
logs e historial Git. El flujo formal del plugin Codex Security no pudo ejecutarse:
no estaban disponibles sus herramientas de scan ni la referencia requerida
`references/scan-prologue.md`; no se atribuye a ese flujo un informe o resultado.
No se ejecutaron payloads contra servicios reales ni se enviaron datos privados.

Modelo de confianza: datos y archivos locales pueden contener información privada;
las vacantes/páginas/prompts externos pueden contener instrucciones adversarias.
Actualmente el evaluador es determinista y no llama modelos ni herramientas.
El navegador solo se abre desde una acción explícita de GUI con URL Google
construida internamente. El actualizador ejecuta Git mediante lista de argumentos,
sin shell, validando origen/rama/limpieza e imponiendo timeout; los launchers
pueden instalar el paquete local y reparar `.venv`, por eso se inspeccionaron
antes de ejecutar el camino de preparación con un entorno sano.

La revisión histórica recorrió `git rev-list --all`, `git ls-tree -r <commit>`
y `git cat-file blob <oid>` para los 90 commits/100 blobs únicos. Se buscaron
cabeceras de claves privadas, patrones GitHub/AWS/API/Telegram, asignaciones
literales de credenciales, emails, URLs localhost/RFC1918 y rutas `.env`, claves,
SQLite, PDF y documentos de oficina. No se imprimieron valores coincidentes.
Solo hubo coincidencias de patrón email por la sintaxis SSH `git@github.com`
en `scripts/auto_update.py` y sus pruebas, presentes en la base `54c7c9e`;
no son credenciales ni datos de contacto personales. Sin coincidencias de los
patrones de secretos o rutas sensibles buscados. No se recomienda rotación
sin evidencia de una exposición. Esta búsqueda heurística no prueba ausencia
universal de secretos, información personal o referencias privadas.

| Riesgo | Prioridad | Evidencia, alcance y siguiente acción |
| --- | --- | --- |
| Prompts con contenido externo | Media antes de integrar IA | Delimitan vacante/CV y exigen honestidad, pero no neutralizan instrucciones adversarias; hoy solo uso manual. Añadir pruebas adversariales y separar instrucciones/datos antes de dar herramientas |
| Datos y logs locales | Media | `config.py` usa escrituras directas y permisos por umask; launchers escriben rutas y excepciones en logs del checkout sin patrón de ignore. Riesgo de compartición accidental; permisos/reducción de logs antes de operación continua |
| Envíos sin aprobación | Sin camino de envío actual; control futuro obligatorio | No hay cliente HTTP de candidaturas, correo o Telegram. `DRY_RUN`/`AUTO_SUBMIT` son requisitos documentados, no variables consumidas hoy. Implementar autorización por CV/vacante antes de añadir un emisor |
| SQL y comandos | Controles presentes, revisión estática | Valores SQL parametrizados; columnas de UPDATE seleccionadas internamente. Git usa argumentos explícitos. No se detectó un camino de inyección desde la vacante hasta shell/SQL |
| Cadena de suministro | Baja en runtime; pendiente en herramientas | `dependencies=[]`; extras dev/build sin lock. SHA de Actions y `contents: read` conservados; no se verificó criptográficamente todo artefacto instalado |
| Disponibilidad/red de futuras fuentes | Media | Cloud tiene red restringida: hosts ATS/Telegram no están en la lista del executor. Lectura web de investigación no prueba conectividad de runtime; resolver acceso y términos en fases autorizadas, sin evadir proxy |
| Persistencia y concurrencia | Alta para automatizar | Duplicados y versión sobrescrita reproducidos; no hay backup/restauración operativa ni exclusión mutua. Resolver antes de scheduler |

`pip check` no es una comprobación de vulnerabilidades. La consulta separada de
metadatos de seguridad de PyPI para herramientas instaladas se registra abajo.
No se auditó el código completo de dependencias de desarrollo/transitivas,
componentes del sistema operativo, PyInstaller no instalado ni los cinco
proyectos externos; la investigación de estos últimos solo revisó metadatos,
README y licencia, sin instalar ni ejecutar nada.

## Fuentes públicas y acceso pendiente

Consulta documental, sin implementar conectores ni consultar APIs de vacantes:

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html): GET de
  tableros públicos sin autenticación según documentación; POST de candidaturas
  es una operación separada. Revalidar términos y uso por organización en Fase 2.
- [Lever Postings API](https://github.com/lever/postings-api): API para
  publicaciones; no confundir lectura de ofertas con enviar una candidatura.
- [Ashby Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api):
  endpoint de lectura por nombre de tablero; campos ausentes pueden quedar vacíos.

Los tres tableros y limitaciones se registran en `sources/companies.yaml`.
GitLab devuelve un tablero con puestos restringidos por país; dLocal muestra
un tablero vacío; Supabase confirma enlaces Ashby en su página oficial, pero
el tablero requiere JavaScript para listar. Todos mantienen elegibilidad regional
pendiente y ejecución desactivada. No se presupone permiso de contratación en
México, disponibilidad gratuita de todas las APIs ni vigencia de ofertas no leídas.
Remotive, Remote OK, Get on Board y Working Nomads quedan para evaluación
individual en Fase 2. No se solicitaron tokens o accesos de producción.

## Dependencias: consulta de avisos publicados

Se consultó por HTTPS `https://pypi.org/pypi/{name}/{version}/json` para las
13 herramientas/transitivas instaladas en `.venv`, excluyendo el paquete local.
Las 12 entradas de avisos para **pip 25.0.1** corresponden a seis CVE únicos:
CVE-2025-8869, CVE-2026-1703, CVE-2026-3219, CVE-2026-6357,
CVE-2026-8643 y CVE-2026-13346. El resto de las versiones consultadas devolvió
`vulnerabilities: []`; esto significa ausencia de avisos en esa fuente/fecha,
no prueba de ausencia de vulnerabilidades.

Fuente: [metadatos de pip 25.0.1 en PyPI](https://pypi.org/pypi/pip/25.0.1/json).
Los avisos afectan extracción/instalación de archivos y, en un caso, índices
maliciosos. La mitigación por PEP 706 del aviso CVE-2025-8869 aplica al Python
3.12 observado según sus metadatos; no se extrapola a los otros avisos. Las
versiones de corrección publicadas llegan hasta pip 26.2.0 para ese conjunto.
Prioridad media de mantenimiento del entorno: actualizar pip a una versión
revisada que cubra esos avisos antes de instalar artefactos no confiables.
No se modificó el entorno ni se ejecutó una explotación. pip no es una
dependencia de runtime del buscador y estos avisos no prueban explotación del
repositorio o exposición remota de su CLI.

Comando de consulta ejecutado (cuatro lecturas simultáneas, timeout de 15 s):

```bash
python3 - <<'PY'
import concurrent.futures, json, subprocess, urllib.request
packages = json.loads(subprocess.check_output(
    ['.venv/bin/python', '-m', 'pip', 'list', '--format=json'], text=True))
packages = [p for p in packages if p['name'] != 'job-search-assistant']
def check(package):
    url = 'https://pypi.org/pypi/{name}/{version}/json'.format(**package)
    with urllib.request.urlopen(url, timeout=15) as response:
        data = json.load(response)
    return package['name'], package['version'], [
        item['id'] for item in data.get('vulnerabilities', [])]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for result in pool.map(check, packages):
        print(result)
PY
```

## Recorrido CLI sintético adicional

Se ejecutaron ocho procesos CLI, todos con salida 0, dentro de un único
`TemporaryDirectory` usado como `JOB_SEARCH_ASSISTANT_HOME`. Incluyeron un
segundo guardado secuencial, actualización de estado **local**, listado y ambos
formatos de exportación. Se verificó un solo registro persistido y estado `applied`
tras reiniciar cada proceso. Esto confirma la protección secuencial de la CLI;
no contradice la falta de unicidad en la API de base de datos.

```bash
python3 - <<'PY'
import json, os, subprocess, tempfile
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='jobsearch-phase1-cli-') as directory:
    env = dict(os.environ, JOB_SEARCH_ASSISTANT_HOME=directory)
    def run(*args):
        result = subprocess.run(
            ['.venv/bin/python', '-m', 'jobsearch_assistant', *args],
            env=env, capture_output=True, text=True)
        assert result.returncode == 0, (args, result.returncode, result.stderr)
        return result.stdout
    run('init', '--language', 'es')
    run('profile', 'import', 'examples/profile.example.json')
    args = ('analyze', 'examples/job-posting.txt', '--title',
            'Synthetic Junior Support', '--company', 'Synthetic Example',
            '--location', 'Remote - Mexico', '--url',
            'https://example.invalid/jobs/synthetic', '--save')
    run(*args)
    assert 'Duplicate application already exists' in run(*args)
    run('applications', 'update', '1', '--status', 'applied',
        '--notes', 'Synthetic local tracker note')
    assert 'Synthetic Example' in run('applications', 'list', '--status', 'applied')
    for kind in ('json', 'csv'):
        run('export', '--format', kind, '--output',
            str(Path(directory) / ('applications.' + kind)))
    records = json.loads((Path(directory) / 'applications.json').read_text())
    assert len(records) == 1 and records[0]['status'] == 'applied'
PY
```

## Validación final de archivos de esta entrega

Los dos YAML se analizaron con `yaml.safe_load`, usando Python del sistema y
PyYAML 6.0.3 ya disponible, sin añadir dependencias al proyecto. Se comprobaron
perfil sintético, flags booleanos seguros, tres tableros con evidencia, todos
deshabilitados y con elegibilidad regional pendiente. Comando reproducible:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml
profile = yaml.safe_load(Path('profile.example.yaml').read_text())
catalog = yaml.safe_load(Path('sources/companies.yaml').read_text())
assert profile['schema_version'] == catalog['schema_version'] == 1
assert profile['synthetic'] is True
assert profile['safety']['dry_run'] is True
assert profile['safety']['auto_submit'] is False
assert catalog['enabled'] is False and len(catalog['companies']) == 3
for company in catalog['companies']:
    assert company['enabled'] is False
    assert company['regional_eligibility_status'] == 'pending'
    assert company['board_status'] in catalog['verification_states']['board_status']
    assert company['evidence_sources'] and company['board_url'].startswith('https://')
print('YAML válido; perfil sintético y catálogo deshabilitado.')
PY
```

`git diff --check` terminó con salida 0. Tras escribir los documentos y YAML,
se repitieron `unittest` (29 OK), `pytest` (31 y 106 subtests OK), `pip check`
y compilación, sin fallos. El diff se limita a `AGENTS.md`, `PLAN.md`, este
registro de evidencia y los dos YAML. No se modificaron Python, scripts,
workflows, dependencias, datos privados ni el esquema persistente.

La revisión manual debe confirmar límites de alcance, referencias de fuentes,
elegibilidad pendiente, datos sintéticos, precedencia de exclusiones, separación
entre políticas y controles implementados, y resultados de CI del PR. No hubo
revisión de Claude, candidaturas, correos, notificaciones o despliegue en PizzaLab.
La Fase 2 requiere integrar esta entrega y autorizar su alcance.
