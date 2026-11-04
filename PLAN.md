# Plan técnico: automatización de búsqueda de empleo

Fecha de auditoría: 2026-11-04. Base: `main` en
`54c7c9ee21fd88625386799782f40da8b6882a5d`.

**Única fase autorizada en esta entrega: Fase 1, auditoría y planificación.**
Los componentes y contratos futuros descritos aquí no están implementados.
Cada fase termina en un PR a `main`; no fusionar automáticamente ni comenzar
una fase dependiente hasta integrar su requisito y obtener autorización de alcance.

## Estado actual verificado

Existe una aplicación Python 3.10+ con CLI, GUI Tkinter bilingüe, perfil JSON,
evaluador determinista, tracker SQLite, exportación CSV/JSON, enlaces de búsqueda,
prompts manuales y launchers Windows/Linux. No hay dependencias de runtime.
No es necesario reconstruir estos componentes.

En Linux/Python 3.12.14 pasan 29 pruebas `unittest` y 31 pruebas `pytest`
(106 subtests), diagnóstico, compilación y preparación Linux sin ventana.
No se validó una sesión gráfica interactiva ni Windows en este entorno.
CI define seis combinaciones Windows/Ubuntu y Python 3.10/3.12/3.13, pero
su comando `unittest` omite las dos pruebas de exportación escritas como funciones.

No existen conectores ATS, scheduler de búsqueda, Telegram, generación integrada
de CV, aprobación por versión de CV, migraciones incrementales, bloqueo de
concurrencia o despliegue PizzaLab. Los YAML de esta fase son contratos de
planificación editables: la aplicación actual solo importa perfiles JSON.

Inventario, comandos, reproducciones, riesgos y límites en
[la auditoría de Fase 1](docs/PHASE_1_AUDIT.md). La comparación breve de los cinco
proyectos externos se conserva en la descripción del PR de esta fase.

## Decisiones aprobadas y compatibilidad

- Python como lenguaje principal y SQLite como único motor persistente.
  Conservar biblioteca estándar en runtime salvo beneficio justificado.
- Conservar CLI/Tkinter, inglés/español, almacenamiento privado externo mediante
  `JOB_SEARCH_ASSISTANT_HOME`, validación de perfiles JSON y recuperación sin
  reescritura de archivos inválidos. No reemplazar JSON por YAML silenciosamente.
- Conservar exportación CSV protegida contra fórmulas, SQL parametrizado,
  actualizador conservador y acciones CI fijadas por SHA con `contents: read`.
  Las mejoras históricas de agosto/septiembre están integradas; el
  [PLAN anterior](https://github.com/alpizars2005-oss/job-search-mx-assistant/blob/54c7c9ee21fd88625386799782f40da8b6882a5d/PLAN.md)
  queda disponible como evidencia histórica.
- Fuentes candidatas: Greenhouse, Lever y Ashby primero; Remotive, Remote OK,
  Get on Board y Working Nomads solo tras verificar APIs/feeds y términos.
  No scraping de LinkedIn/Indeed, sesiones privadas, CAPTCHA o evasión antibot.
- `DRY_RUN=true`, `AUTO_SUBMIT=false`; una autorización futura identifica
  empresa, vacante y versión concreta del CV. No responder evaluaciones.
- Telegram como primera notificación, desactivada sin configuración autorizada.
- Codex desarrolla; Claude Code será revisor independiente en Fase 5 mediante
  integración oficial compatible con Cloud. No se instaló ni configuró ahora.
- Producción futura en PizzaLab/Proxmox VE: LXC Debian 12 sin privilegios,
  systemd service/timer, SQLite persistente y backups `.backup` restaurables.
  Sin PostgreSQL, Redis, brokers, colas distribuidas ni microservicios.

## Arquitectura objetivo propuesta

Extender el núcleo existente como una sola aplicación. Los adaptadores de lectura
reciben configuración de fuentes y devuelven vacantes normalizadas; no reciben
CV ni credenciales de envío. Separar procedencia/vigencia, elegibilidad y matching
del seguimiento de candidaturas.

1. **Fuentes (Fase 2):** adaptadores por proveedor, validación de respuestas,
   normalización y deduplicación en memoria. Campos propuestos: `source`,
   `source_job_id`, `company`, `title`, `locations`, `work_mode`, `url`,
   `description`, `published_at`, `retrieved_at`, `verification_status`,
   `eligibility_evidence`. Identificadores y evidencia explícitos; fechas/condiciones
   desconocidas permanecen desconocidas. No añadir tablas en esa fase.
2. **Persistencia y matching (Fase 3):** extender `database.py` y los modelos
   existentes con vacantes/fuentes, evidencia, evaluaciones versionadas y claves
   únicas. Migraciones secuenciales transaccionales con backup previo; rechazar
   versiones futuras desconocidas y preservar registros históricos.
   Elegibilidad primero; puntuación después, según `AGENTS.md`.
3. **Candidaturas (Fase 4):** CV maestro externo al repositorio, versiones y
   huellas de contenido, borradores y tracker reutilizado. Autorización explícita
   enlazada a empresa/vacante/CV y consumida una sola vez; cancelar autorización
   al cambiar contenido. No incorporar envío real como consecuencia de guardar
   un registro con estado `applied`.
4. **Operación (Fase 5):** comando de ejecución idempotente, exclusión mutua
   local, resumen, logs redactados, health check y notificador opcional.
   Un timer ejecutará ese mismo comando en Fase 6; no sumar otro scheduler
   residente ni una cola distribuida. Evaluar revisión oficial de Claude en PRs.
5. **Producción (Fase 6):** CLI sin GUI en el LXC, usuario de servicio sin
   privilegios y código fijado a una versión revisada. Datos persistentes fuera
   del checkout. No usar launchers de escritorio con autoactualización como
   servicio de producción. Backups con `.backup`, retención, permisos y prueba
   de restauración; no copiar solo el archivo principal de SQLite con WAL activo.

Flujo previsto: fuente no confiable → validación/normalización → evidencia de
vigencia/elegibilidad → matching explicable → SQLite/tracker → borradores →
autorización específica antes de cualquier envío. Las notificaciones no autorizan
postulaciones. No se requiere un servidor HTTP ni puertos de entrada.

No se encontró un bloqueo fundamental con Debian 12/Python 3.11 y SQLite.
Esto es compatibilidad estática; no constituye una prueba de instalación en LXC.

## Problemas conocidos y prioridad

Prioridades de ingeniería, no puntuaciones de vulnerabilidad:

- **Alta:** `not remote` y una vacante exclusiva de EE. UU. pueden dar `100/100`;
  falta evaluación excluyente y estado de información insuficiente. Resolver
  antes de utilizar el score como filtro automático en Fase 3.
- **Alta:** deduplicación separada del INSERT, sin restricción única; no garantiza
  idempotencia ante concurrencia. Resolver en Fase 3 antes de automatizar.
- **Alta:** `initialize()` sobrescribe `schema_version` a 1; no es un motor de
  migraciones. Corregir antes de evolucionar el esquema en Fase 3.
- **Media:** pip 25.0.1 del entorno tiene avisos publicados en PyPI; actualizar
  herramientas de instalación antes de incorporar artefactos no confiables. No
  confundirlo con una dependencia de runtime. Detalle y límites en la auditoría.
- **Media:** CI omite pruebas CSV, y la CLI/GUI no tienen cobertura integral.
  Incorporar las pruebas existentes de exportación a CI en una entrega futura.
- **Media:** prompts manuales sin aislamiento explícito frente a instrucciones
  externas; revisión adversarial obligatoria antes de conectarlos a herramientas.
- **Media:** permisos dependen de umask, escrituras JSON no atómicas y logs de
  launcher en checkout sin ignorar. Endurecer antes de operación continua.
- **Baja:** normalización de texto repetida, documentación de roadmap anterior
  más amplia que estas fases y 13 diagnósticos Ruff preexistentes. No refactorizar
  funcionalidad ni cambiar herramientas durante esta entrega documental.

## Fases, entregables y criterios de aceptación

### Fase 1 — Auditoría y planificación (esta entrega)

Entregables: `AGENTS.md`, este `PLAN.md`, `profile.example.yaml`,
`sources/companies.yaml`, registro verificable de auditoría y un PR documental
con una sola tabla comparativa de los cinco repositorios externos.

- [x] Inspeccionar repositorio completo, scripts, pruebas, CI e historial disponible.
- [x] Ejecutar validaciones seguras y clasificar componentes y riesgos.
- [x] Documentar arquitectura aprobada y próximos hitos sin implementarlos.
- [x] Validar los YAML, privacidad y diff final; ejecutar controles pertinentes.
Cierre: commits atómicos y PR a `main`, con hashes y resultados en la descripción
del PR y el resumen de entrega. Después, detenerse.

### Fase 2 — Fuentes de vacantes (pendiente, no iniciada)

Requiere Fase 1 integrada y autorización para esta fase. Evaluar acceso/términos
de cada fuente, validar identificadores del catálogo y confirmar permisos de red
de Cloud. Ningún tablero confirmado implica elegibilidad desde México.

Tareas/commits propuestos:

1. `test: cover source contracts and include export tests in CI`: casos sintéticos
   de payload válido/inválido, vacío, HTML inesperado, redirección fuera del ATS,
   timeout, 429/`Retry-After`, 5xx y paginación limitada; ejecutar también las
   dos pruebas CSV ya existentes. No contactar producción en CI.
2. `feat: add bounded public ATS readers`: empezar por Greenhouse, después Lever
   y Ashby en commits pequeños. Solo endpoints de lectura oficialmente permitidos;
   validar host, esquema y tamaño, sin seguir URLs arbitrarias de la respuesta.
   Propuesta configurable: 20 solicitudes/fuente/ejecución, timeout 15 s,
   3 reintentos, backoff exponencial con jitter y pausa a los 5 errores consecutivos.
   Revisar esos valores contra términos de cada proveedor; un `Retry-After` que
   exceda el presupuesto pospone la fuente, no se ignora.
3. `feat: normalize and deduplicate source postings`: clave estable
   `(source, source_job_id)`, URL canónica sin destruir identificadores sensibles
   a mayúsculas, normalización explícita de ubicaciones y evidencia. Preservar
   procedencia y contenido desconocido; no inferir México de la palabra remoto.
4. `docs: explain source access and validation`: instrucciones reproducibles y
   fuentes deshabilitadas por defecto hasta configuración autorizada.

Aceptación: respuestas sintéticas, validación de entradas, deduplicación
reproducible, límites/reintentos/circuit breaker probados, ningún scraping
prohibido y contenido externo tratado como datos. Conservar pruebas actuales.
Una consulta real solo se reportará validada si se ejecuta con acceso permitido.

### Fase 3 — SQLite y matching (pendiente)

Requiere Fase 2 integrada. Commits propuestos: pruebas de migración/backup,
migraciones versionadas y unicidad, persistencia de evidencia, elegibilidad
excluyente, scoring/configuración y adaptación de CLI/GUI.

Aceptación: migración desde esquema 1 sin pérdida; rollback documentado;
persistencia tras reinicio; rechazar versión futura; ausencia de duplicados aun
con dos escritores; puntajes reproducibles y explicaciones coherentes. Probar
negaciones, EE. UU. exclusivo, título obligatorio, experiencia incompatible,
salario desconocido e información esencial faltante. Las seis clasificaciones
objetivo de `AGENTS.md` tienen precedencia explícita; no reinterpretar resultados
históricos sin versionar el algoritmo.

### Fase 4 — Candidaturas y tracker (pendiente)

Requiere Fase 3 integrada. Commits: versiones de CV con evidencia, borradores y
exportación, estados/transiciones y aprobación específica vinculada al contenido.

Aceptación: datos sintéticos, CV/candidatura trazables, ningún dato inventado,
transiciones válidas, detección de repetidos y ningún envío no autorizado.
Cambiar la versión del CV invalida aprobación; guardar o cambiar estado local
no envía nada. No responder evaluaciones de selección automáticamente.

### Fase 5 — Automatización, Telegram y revisión independiente (pendiente)

Requiere Fase 4 integrada. Commits: ejecución periódica idempotente, bloqueo
local y recuperación, logs/health checks, Telegram opt-in y revisión oficial
de Claude Code mediante GitHub Actions u opción equivalente de Cloud.

Aceptación: sin carreras entre ejecuciones; recuperación tras fallo; notificaciones
con configuración de prueba autorizada; sin secretos en logs; integración de
revisión verificable cuando exista acceso. No asumir Claude CLI ni contratar
servicios. Aislar secretos de jobs que procesan PRs no confiables.

### Fase 6 — Preparación y despliegue PizzaLab (pendiente)

Requiere fases previas integradas y autorización/acceso explícitos al destino.
Commits: manual `DEPLOYMENT`, unidades service/timer, persistencia/permisos,
backup/restauración y procedimiento de rollback de código y esquema.

Aceptación: instalación reproducible en LXC Debian 12 de prueba sin privilegios;
servicio reiniciable y timer verificado; backups consistentes y restauración
ejecutada; recursos controlados; sin puertos innecesarios; rollback probado.
Despliegue real solo confirmado con evidencia y acceso autorizado a PizzaLab.

## Commits y cierre de esta fase

1. `docs: establish phase-one audit and implementation roadmap`: reglas, plan
   y auditoría con comandos/resultados reales, conservando decisiones previas.
2. `docs: add synthetic profile and verified source candidates`: dos YAML de
   planificación y su validación, sin loaders ni nuevas dependencias.

Antes del PR: revisión de coherencia, privacidad y prompts, YAML válido, pruebas
existentes, diff sin código funcional, `git diff --check` y comprobación de que
solo cambia el alcance autorizado. Volver a consultar `main` antes de publicar;
no sobrescribir cambios concurrentes. Publicar únicamente la rama de esta fase.

Para continuar después: integrar el PR, autorizar Fase 2, revisar términos y red,
revalidar tableros y convertir los casos sintéticos anteriores en pruebas de
contrato. No se necesita un token de Telegram, acceso a PizzaLab o Claude ahora.
