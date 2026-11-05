# Architecture

The project uses a small layered architecture:

- `models.py`: portable domain objects.
- `evaluator.py`: deterministic and explainable fit scoring.
- `database.py`: SQLite persistence and schema management.
- `config.py`: cross-platform data paths and profile/settings files.
- `exporters.py`: CSV and JSON interchange.
- `search_queries.py`: safe, user-initiated search-query generation.
- `cli.py`: automation-friendly interface.
- `gui.py`: Tkinter desktop interface.

The GUI and CLI do not duplicate business logic. Both call the evaluator and database layers directly.

## Design constraints

- Python standard library for the default installation.
- User data outside the repository.
- No mandatory API key.
- No authenticated scraping.
- No automatic application submission.
- Explainable scoring with visible evidence.


## Descubrimiento público implementado en Fase 2 (contrato inicial)

El paquete `sources` permanece separado de los modelos y la base del tracker:

- `models.py`: configuración validada, límites, vacante normalizada y reportes.
- `http.py`: transporte GET urllib sin redirects y cliente con cuotas compartidas,
  timeouts, límite de bytes, reintentos/jitter, Retry-After y pausas en memoria.
- `adapters.py`: endpoints fijos, validación y transformación de cada contrato ATS.
- `discovery.py`: orquestación serial y deduplicación por proveedor/tablero/ID.
- `config.py`: configuración JSON explícita, acotada y separada de perfiles.

`jobsearch discover` usa ese paquete sin abrir SQLite o leer perfiles. La GUI,
evaluador y exportadores históricos conservan sus interfaces. La salida incluye
procedencia por campo y evidencia regional sin interpretación; no conecta el
score anterior a un filtro de elegibilidad. Transporte y reloj son inyectables
para pruebas offline. Ver [contrato y operación](JOB_SOURCES.md).

## Integración implementada en Fase 3

- `eligibility.py`: requisitos excluyentes, negaciones y evidencia de campos o
  fragmentos, conservando desconocidos y contradicciones.
- `matching.py`: compatibilidad determinista `matching_v3` y explicación bilingüe.
- `evaluator.py`: entrada compatible al motor nuevo; `evaluate_job_legacy`
  conserva el algoritmo histórico como referencia explícita.
- `migrations.py`: esquema 2, migración 1→2 transaccional, backup SQLite previo
  y restauración hacia un destino nuevo; rechazo de versiones no soportadas.
- `database.py`: tracker anterior, identidades, vacantes únicas y snapshots de
  evaluaciones con versiones y huellas de contenido.

El flujo opt-in `discover --save` conecta `NormalizedJob` directamente al motor
y a SQLite, sin reducirlo al modelo manual ni perder procedencia. El snapshot
de evaluación identifica el dato realmente evaluado aunque otro proceso actualice
la vacante. `vacancies evaluate` reevalúa explícitamente con el perfil actual y
añade una versión cuando cambian las entradas; no modifica resultados anteriores.
La GUI y `analyze` usan el mismo motor y conservan el tracker manual. Detalles y
límites en [SQLITE_MATCHING](SQLITE_MATCHING.md). No hay servicios nuevos.

## CV y candidaturas implementados en Fase 4

- `workflow_contracts.py`: JSON canónico, hashes de contenido/vacante, errores
  redactados y política local fail-closed.
- `resumes.py` y `resume_documents.py`: maestro bilingüe con evidencia, almacén
  privado inmutable, publicación exclusiva y exportación TXT/DOCX determinista.
- `candidacies.py`: revisiones y snapshots, revisión/digest, autorizaciones de
  un uso, simulación sin sender y consulta consistente del historial.
- `migrations.py`/`database.py`: esquema 3 aditivo, backup previo, tracker gestionado
  con transiciones y restauración que revoca capacidades en un destino nuevo.
- `drafts.py`/`workflow_cli.py`: composición literal de hechos y comandos opt-in;
  importación manual offline sin seguir URLs. CLI/GUI previas usan el mismo tracker.

Los archivos se publican antes de insertar metadata que los referencie. Un crash
puede dejar archivos huérfanos privados, nunca una referencia válida a un documento
parcial. Un recibo de simulación no representa una operación externa. La futura
entrega a un ATS requiere diseño/autorización propios; no se disfraza como consumo
SQLite una garantía de exactly-once sobre un servicio remoto. Ver
[contrato de operación](RESUMES_CANDIDACIES.md).

## Operación implementada en Fase 5

- `runtime_control.py`: presupuesto/cancelación, mutex OS y HTTP en worker spawn.
- `sources/http.py`: estado UTC exportable/importable y checkpoints durables; el
  contrato anterior sin control continúa disponible.
- `automation_schema.py`/`automation_store.py`: esquema 5, historial y observación
  atómica reutilizando upsert/invalidation/evaluation internos de Fases 3–4.
- `automation.py`/`automation_cli.py`: una ejecución finita, callbacks por página,
  logs allowlist, perfil estricto y lecturas operativas sin migración.
- `private_storage.py`: validación y apertura privada compartida, SQLite y sidecars.
- `legacy_notifications_schema.py`: DDL histórico y triggers de retirada; sin runtime.
- `operational_control_events`: historial inmutable de recuperación manual de fuentes.
- Workflow Claude manual y preparador confiable: diff acotado tratado como datos,
  sin extraer código del PR ni herramientas para modificarlo; default desactivado.

No hay daemon, servicio nuevo, scheduler residente o despliegue. El punto de entrada
podrá invocarse desde un timer autorizado en Fase 6. Ver [operación](AUTOMATION_MONITORING.md).
