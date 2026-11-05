# Plan técnico: automatización de búsqueda de empleo

Fecha de auditoría de Fase 1: 2026-11-04. Base histórica: `main` en
`54c7c9ee21fd88625386799782f40da8b6882a5d`.

**Fase actualmente autorizada: Fase 6, hardening y preparación operativa.**
PR #10 integrado en main `cfa6a4d974ce129a2bc8aeeb4ee4d53b6afc44f7`, CI74 correcto.
La misión nueva permite ramas/PRs apilados con dependencia explícita, sin fusiones.

## Estado de hardening de Fase 6 (propuesto, pendiente de integración)

M-01 versiona matching_v3 sin cambiar snapshots anteriores. M-02 separa cancelación
local de fallos de proveedor y conserva respuestas/límites ya recibidos. M-03 aplica
almacenamiento privado común. Telegram se retira: historial protegido por esquema 5,
sin transporte ni productores. Retry-After extremo queda suspendido para revisión;
health distingue ejecución activa y abandono. Claude continúa desactivado con
checks de debug adicionales. CI exige ocho combinaciones de Python/OS.
Ver [operación](docs/AUTOMATION_MONITORING.md) y
[plan](docs/superpowers/plans/2026-11-04-phase6-hardening.md).
Infraestructura y reportes diarios están preparados en entrega apilada dependiente;
no hay despliegue, acceso PizzaLab, mensajes ni revisión real de Claude en esta misión.

## Estado de preparación B (propuesto, no integrado)

Unidades systemd oneshot y timers horario/diario, release offline fijada por SHA,
instalador/preflight Debian 12/Python 3.11 y rollback compatible. Reportes privados
JSON/Markdown 14:00 America/Mexico_City con catchup/idempotencia y distinción de
simulaciones/manual-applied/envíos confirmados 0. Backup conjunto hash/verificado,
restore a destino nuevo con revocación/cuarentena, retención solo inventario.
Work investigado: sin acceso LXC/endpoint autorizado verificable, fallback local
completo y ningún transporte activado. [Despliegue](docs/DEPLOYMENT.md),
[reportes](docs/DAILY_REPORTS.md), [recuperación](docs/STORAGE_RECOVERY.md).
HARDENING PENDIENTE mientras los PRs no estén integrados; no declarar producción.


## Estado de Fase 5 (histórico, integrado en PR #10)

Ejecución finita, persistencia HTTP, recuperación y observabilidad. Su Telegram
opt-in queda sustituido por la retirada definitiva de Fase 6. El estado original
se conserva en Git y no debe usarse como procedimiento de activación actual.

## Estado de Fase 4 (histórico, integrada en PR #9)

Almacén privado de maestros ES/EN con evidencia y atestación, versiones TXT/DOCX
direccionadas por contenido y adaptación mediante selección de hechos. Borradores
y tracker reutilizan SQLite esquema 3, con historial inmutable, revisión exacta y
autorizaciones consumibles una vez mediante simulación local. No hay sender.
Migración desde 1/2 con backup previo, rollback y revocación de capacidades al
restaurar un backup. Nuevos flujos CLI, preservación del tracker GUI y políticas
DRY_RUN/AUTO_SUBMIT verificadas. Operación y límites en
[CV y candidaturas](docs/RESUMES_CANDIDACIES.md); diseño y pasos en
[plan de Fase 4](docs/superpowers/plans/2026-11-04-resumes-applications.md).
La evidencia final de revisión, pruebas y CI se registra en su PR independiente.

## Estado de Fase 3 (histórico, integrada en PR #8)

Contratos compatibles con perfiles JSON anteriores; esquema 2 con migración
transaccional, backup previo, identidades únicas y evaluaciones con snapshots.
Elegibilidad previa al scoring, seis clasificaciones y algoritmo `matching_v2`;
los históricos conservan `legacy_v1` sin reevaluación. CLI/GUI comparten motor;
`discover --save` conecta los tres ATS a persistencia y evaluación mediante una
opción explícita. Operación y límites en [SQLITE_MATCHING](docs/SQLITE_MATCHING.md),
plan y verificación en [plan de Fase 3](docs/superpowers/plans/2026-11-04-sqlite-matching.md).
La evidencia final de pruebas y CI se registra en el PR de esta fase.

## Estado de Fase 2 (histórico, integrada en PR #7)

Implementados lectores GET de Greenhouse, Lever y Ashby, transporte acotado,
validación de datos/URLs, normalización con procedencia, deduplicación en memoria,
configuración JSON opt-in y comando `discover`. No se modifican SQLite, perfiles
JSON, matching o GUI. Las dos pruebas CSV ahora son descubiertas por unittest
incluido en CI. Documentación y evidencia en [JOB_SOURCES](docs/JOB_SOURCES.md);
plan de ejecución en [plan de Fase 2](docs/superpowers/plans/2026-11-04-job-sources.md).
Las consultas reales desde Cloud no obtuvieron datos por restricción de red;
no se declara conectividad de runtime con los proveedores.

## Estado verificado al cierre de Fase 1 (histórico)

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
- Telegram retirado definitivamente; reportes privados locales y entrega a Work
  solo cuando exista mecanismo oficial, acceso y autorización comprobados.
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

## Hallazgos de auditoría y seguimiento

Prioridades de ingeniería, no puntuaciones de vulnerabilidad:

- **Resueltos en Fase 3:** precedencia de exclusiones e información insuficiente,
  unicidad transaccional y validación/migración del marcador de esquema. Las reglas
  de lenguaje son acotadas; ambigüedades no reconocidas aún requieren revisión.
- **Media:** pip 25.0.1 del entorno tiene avisos publicados en PyPI; actualizar
  herramientas de instalación antes de incorporar artefactos no confiables. No
  confundirlo con una dependencia de runtime. Detalle y límites en la auditoría.
- **CSV incorporado en Fase 2:** unittest ejecuta sus pruebas en CI. Fase 3 añade
  regresiones CLI, exportaciones y métodos GUI sin ventana; una sesión gráfica
  interactiva sigue requiriendo validación manual.
- **Media:** prompts manuales sin aislamiento explícito frente a instrucciones
  externas; revisión adversarial obligatoria antes de conectarlos a herramientas.
- **Media:** permisos dependen de umask, escrituras JSON no atómicas y logs de
  launcher en checkout sin ignorar. Endurecer antes de operación continua.
- **Baja:** normalización de texto repetida, documentación de roadmap anterior
  más amplia que estas fases y 13 diagnósticos Ruff preexistentes. No refactorizar
  funcionalidad ni cambiar herramientas durante esta entrega documental.

## Fases, entregables y criterios de aceptación

### Fase 1 — Auditoría y planificación (integrada, PR #6)

Entregables: `AGENTS.md`, este `PLAN.md`, `profile.example.yaml`,
`sources/companies.yaml`, registro verificable de auditoría y un PR documental
con una sola tabla comparativa de los cinco repositorios externos.

- [x] Inspeccionar repositorio completo, scripts, pruebas, CI e historial disponible.
- [x] Ejecutar validaciones seguras y clasificar componentes y riesgos.
- [x] Documentar arquitectura aprobada y próximos hitos sin implementarlos.
- [x] Validar los YAML, privacidad y diff final; ejecutar controles pertinentes.
Cierre: commits atómicos y PR a `main`, con hashes y resultados en la descripción
del PR y el resumen de entrega. Después, detenerse.

### Fase 2 — Fuentes de vacantes (integrada, PR #7)

Requisito satisfecho: Fase 1 integrada y Fase 2 autorizada explícitamente. Evaluar acceso/términos
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

### Fase 3 — SQLite y matching (integrada, PR #8)

Requisito comprobado: PR #7 integrado y misión de Fase 3 autorizada. Commits: contratos,
migraciones versionadas y unicidad, persistencia de evidencia, elegibilidad
excluyente, scoring/configuración y adaptación de CLI/GUI.

Aceptación: migración desde esquema 1 sin pérdida; rollback documentado;
persistencia tras reinicio; rechazar versión futura; ausencia de duplicados aun
con dos escritores; puntajes reproducibles y explicaciones coherentes. Probar
negaciones, EE. UU. exclusivo, título obligatorio, experiencia incompatible,
salario desconocido e información esencial faltante. Las seis clasificaciones
objetivo de `AGENTS.md` tienen precedencia explícita; no reinterpretar resultados
históricos sin versionar el algoritmo.

### Fase 4 — Candidaturas y tracker (integrada, PR #9)

Requisito comprobado: PR #8 integrado y CI de main satisfactorio. Commits: contratos,
versiones de CV con evidencia, borradores y
exportación, estados/transiciones y aprobación específica vinculada al contenido.

Aceptación: datos sintéticos, CV/candidatura trazables, ningún dato inventado,
transiciones válidas, detección de repetidos y ningún envío no autorizado.
Cambiar la versión del CV invalida aprobación; guardar o cambiar estado local
no envía nada. No responder evaluaciones de selección automáticamente.

### Fase 5 — Automatización y revisión independiente (histórico)

Requisito comprobado: Fase 4 integrada, CI 71 satisfactorio y misión autorizada.
Commits: ejecución periódica idempotente, bloqueo
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

## Commits y cierre de Fase 1 (histórico)

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


## Entrega de Fase 2 y preparación de Fase 3

- Transporte GET compartido: 20 solicitudes/proveedor/ejecución, 15 s, tres
  reintentos, jitter, Retry-After íntegro, circuit breaker y límites de cuerpo.
- Adaptadores: Greenhouse/Ashby listado completo; Lever con skip/limit,
  límite de páginas y señal explícita de resultados parciales.
- Normalización: identidad estable por proveedor/tablero, campos desconocidos
  explícitos, procedencia por campo, elegibilidad México siempre desconocida.
- Configuración: JSON separado de perfiles, desactivado por defecto y sin URLs
  arbitrarias; sin dependencias adicionales.
- CLI y documentación de fuentes diferidas; tests sintéticos y CSV incluidos en CI.
- Commits realizados y resultados finales se registran en el PR de esta fase.

Al cierre histórico de Fase 2, la Fase 3 no había comenzado. Su requisito era:
conservar los contratos de `NormalizedJob`, añadir persistencia y migraciones
versionadas, claves únicas transaccionales y elegibilidad explicable. No tratar
`listed` como prueba de contratación permitida o el score histórico como filtro
excluyente. Antes de validación real, configurar acceso de red por el mecanismo
autorizado de Cloud y revalidar los términos de cada tablero.

## Continuación después de Fase 3 (histórico)

Integrar su PR tras revisión y autorizar Fase 4 antes de cambiar código dependiente.
Reutilizar identidades y snapshots para versiones de CV/borradores; una evaluación
o estado local jamás autoriza un envío. No hay scheduler, Telegram, integración de
Claude, despliegue ni cambios en PizzaLab en Fase 3.

## Continuación después de Fase 4 (histórico)

Integrar su PR tras revisión y autorizar Fase 5 antes de cambios dependientes.
Reutilizar el workflow exacto y la política segura; los recibos de simulación no
son envíos ni autorizaciones para otra versión. Antes de cualquier sender futuro,
definir transporte, entrega de bytes aprobados, recuperación y deduplicación de
efectos externos; esta fase no resuelve una transacción distribuida con un ATS.
No activar Telegram, Claude o un scheduler por consecuencia de guardar borradores.
No hay despliegue ni cambios en PizzaLab.

## Continuación después de Fase 5

Fase 6 autorizada para preparación: integrar hardening tras revisión, validar LXC
Debian 12/Python 3.11 y red real, instalar versión fijada, recursos, permisos, backups,
retención y rollback. No activar timers antes del piloto autorizado. Claude y Work
requieren permisos y configuración separados; Telegram no se utilizará.
