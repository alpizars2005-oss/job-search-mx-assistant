# SQLite y matching explicable — plan de Fase 3

**Objetivo:** extender la aplicación integrada en `5932de7baa9df938d52fcdd6888ed927625bc49a` sin perder históricos, con migración transaccional y elegibilidad previa al scoring.
**Especificación:** misión de Fase 3 adjunta, `PLAN.md` y `AGENTS.md`. Solo Fase 3; PR a main, sin merge, envíos, servicios o cambios en PizzaLab.
**Tecnología:** Python 3.10+, SQLite y biblioteca estándar. Datos de prueba sintéticos en directorios temporales.

## Diseño y decisiones

Conservar modelos/columnas históricos y ampliar contratos con campos opcionales. No reconstruir el tracker ni introducir otro motor. Los registros anteriores conservan su JSON original y versión `legacy_v1`; los nuevos resultados identifican `matching_v2`. La evaluación nueva devuelve las seis clasificaciones aprobadas y distingue hechos observados de desconocidos; un score alto nunca supera una exclusión o ausencia de información esencial.

Se implementarán SQLite y matching como tareas independientes con archivos de escritura separados, usando superpowers:dispatching-parallel-agents; la integración, revisión de datos y publicación quedan a cargo del agente principal. Todos los implementadores aplican TDD y no modifican Git compartido. Una revisión independiente de toda la rama comprueba la integración final.

## Contratos compartidos

- `CandidateProfile`: conservar campos actuales; añadir `residence_country: str|None`, `work_authorized_countries: list[str]|None`, `experience_years: float|None`, `degree_completed: bool|None`, `language_levels: dict[str,str]`, `conditions: dict[str,bool|None]`, con defaults desconocidos y validación estricta. No inventar experiencia/certificaciones ni inferir permisos del empleador desde el país del candidato.
- `EvaluationResult`: conservar score/recommendation y listas actuales; añadir `algorithm_version='legacy_v1'`, `requirements`, `requirements_met`, `missing_requirements`, `restrictions`, `unknowns`, `evidence`, `suggestions`. Listas vacías por defecto para leer JSON histórico sin reevaluación.
- `matching.evaluate_match(profile, job: JobPosting|NormalizedJob) -> EvaluationResult`: `matching_v2`; `evaluator.evaluate_job` delegará al motor nuevo, y el algoritmo anterior se conserva explícitamente como `evaluate_job_legacy` para equivalencia histórica.
- `ApplicationDatabase`: preservar API CRUD; `add` será idempotente/transaccional, sin borrar duplicados históricos. Añadir `upsert_vacancy(NormalizedJob)->int`, `get_vacancy(id)->NormalizedJob|None`, `list_vacancies()->list[dict]` con `id` y `job` serializado.
- `save_evaluation(vacancy_id, profile, result)->int`, `list_evaluations(vacancy_id)->list[dict]`: versiones, snapshots de oferta/perfil y hashes para reproducibilidad; no sobrescribir evaluación existente para iguales entradas/versión.
- `backup_database(source: Path, destination: Path)->Path`, `restore_backup(source: Path, destination: Path)->Path`: SQLite backup consistente; destino nuevo, nunca sobrescribir una base existente.

## Tareas y commits

### 1. Contratos compatibles (agente principal)

- [ ] Probar primero campos opcionales/tipos, defaults desconocidos y lectura de evaluación histórica.
- [ ] Ampliar `models.py`, preservando JSON existente y tolerancia a campos futuros.
- [ ] Ejecutar suite; commit `feat: extend matching contracts without inventing candidate facts`.

### 2. SQLite y migración segura (tarea independiente)

Archivos: `database.py`, nuevo `migrations.py`, pruebas `test_migrations.py`, `test_persistence.py`. Consumir modelos sin modificarlos.

- [ ] Crear esquema 2 con migración desde 1 en transacción explícita, backup previo y rechazo de versiones desconocidas antes de cambios. No usar executescript que confirme parcialmente una migración.
- [ ] Preservar todos los registros, IDs, timestamps, notas, estados y JSON de evaluación, incluidos duplicados anteriores.
- [ ] Unicidad por proveedor/tablero/ID; deduplicación persistente y dos escritores independientes. No convertir rutas URL sensibles a mayúsculas en minúsculas.
- [ ] Guardar evidencia/snapshots versionados y probar persistencia tras reinicio.
- [ ] Probar fallo y salida abrupta durante migración, recuperación, backup con WAL y restauración en destino nuevo. No destruir o reemplazar archivos existentes.
- [ ] Verificar focused tests y entregar cambios sin commit; commit del principal `feat: migrate SQLite safely and persist source evidence`.

### 3. Elegibilidad y matching (tarea independiente)

Archivos: nuevos `eligibility.py`, `matching.py`; pruebas `test_eligibility.py`, `test_matching.py`. Consumir modelos sin modificarlos; el principal adapta el evaluador histórico.

- [ ] Requisitos geográficos, remoto, experiencia, título, seniority, idiomas y condiciones adicionales antes de scoring; estados met/unmet/unknown/contradictory/not_required, evidencia y motivos.
- [ ] No inferir autorización México de ubicaciones o Remote/Global/Americas/LATAM. Negaciones y restricciones explícitas reconocidas con reglas acotadas; texto ambiguo conserva desconocido, sin obedecer instrucciones externas.
- [ ] Seis clasificaciones y prioridades 80/65/50; exclusiones confirmadas preceden al score. Información esencial desconocida -> insufficient_information. Puntuar solo señales conocidas; salario no publicado no implica incumplimiento.
- [ ] Explicaciones y puntos deterministas; no usar fecha actual o servicios externos. Mantener señales útiles de skill/remote/riesgo para las interfaces existentes.
- [ ] Probar casos adversariales bilingües, contradicciones, título con alternativas, experiencia obligatoria frente a deseable, idiomas y datos desconocidos.
- [ ] Verificar focused tests; commit del principal `feat: evaluate eligibility before explainable matching`.

### 4. Integración, documentación y verificación (agente principal)

- [ ] Conectar CLI/GUI al algoritmo nuevo; explicaciones bilingües y actualización explícita de la expectativa legacy review_risk a las nuevas categorías, sin ocultar tests.
- [ ] `discover --save`: opt-in de persistencia; guardar/evaluar datos normalizados. `vacancies list/evaluate` permite consultar/reproducir resultados sin volver a la red. Mantener discover sin escritura por defecto.
- [ ] Operaciones backup/restore seguras y documentación de rollback a versión anterior sobre copia nueva.
- [ ] Conservar campos nuevos al editar perfiles desde GUI; regresiones headless, CLI, CSV/JSON y registros históricos.
- [ ] Documentar migraciones, semántica, límites conservadores, comandos y aceptación; actualizar PLAN/README/SECURITY/CHANGELOG donde corresponda.
- [ ] Suites completas Python 3.10 y 3.12, pytest, compilación y CI Windows/Ubuntu; correcciones y revisión independiente de toda la rama antes de publicar PR sin merge.

## Foco de revisión

- Un backup no debe ejecutarse desde una conexión con escritura activa que bloquee su propio progreso; el snapshot debe incluir commits WAL y preceder a la modificación de esquema.
- Dos inicializadores/escritores deben serializarse sin pérdida ni reescritura de versiones futuras.
- Los datos desconocidos y la negación de requisitos no deben convertirse en coincidencias positivas.
- Una oferta normalizada actualizada no debe alterar el snapshot de una evaluación histórica.
- GUI, exportaciones y perfiles antiguos deben conservar datos y etiquetas al adoptar el nuevo contrato.
