# CV y candidaturas — plan de implementación de Fase 4

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** gestionar CV verificables y candidaturas locales con aprobaciones exactas de un solo uso.
**Architecture:** extender el tracker existente con esquema 3 y un almacén privado de documentos inmutables. Núcleo y CLI comparten contratos; generación determinista y simulación sin sender.
**Tech Stack:** Python 3.10+, SQLite, JSON, hashlib, zipfile y XML de biblioteca estándar.
**Spec:** `docs/superpowers/specs/2026-11-04-resumes-applications-design.md`, misión explícita del usuario y `AGENTS.md`.

## Global Constraints

- No implementar envíos externos reales en esta fase.
- Guardar una candidatura como `applied` nunca debe enviar información.
- Mantener `DRY_RUN=true` y `AUTO_SUBMIT=false` como política obligatoria.
- Almacenar documentos personales fuera del repositorio. No exponer información privada en logs.
- Prohibir información inventada. Proyectos, experiencia y certificaciones tienen categorías y evidencia propias.
- Cada aprobación vincula empresa, identificador de vacante, versión y huella del CV, contenido aprobado e identificador de autorización.
- Si cambia cualquier elemento aprobado, invalidar la autorización.
- Preservar CLI, GUI Tkinter, perfiles JSON, SQLite, exportaciones, idiomas y funcionalidades anteriores.
- No fusiones el PR. No inicies Fase 5 ni Fase 6. No configures Telegram, Claude Code ni PizzaLab.

## Ejecución y contratos compartidos

Usar tareas independientes con archivos separados para almacén CV y SQLite,
según `dispatching-parallel-agents`; el principal implementa contratos, integración,
commits y documentación. Implementadores no modifican Git compartido ni delegan.
Cada tarea aplica TDD; revisión separada de cada subsistema y revisión final de rama.
No se solicita otra aprobación de diseño porque la misión autoriza autonomía.

`workflow_contracts.py` produce:

- `WorkflowError(code)` excepción ValueError con diagnóstico estable sin datos privados.
- `canonical_json(value)->str`, `content_digest(value)->str` SHA256 JSON canónico.
- `vacancy_key(job:NormalizedJob)->list[str]`, `vacancy_digest(job)->str` excluye solo retrieved_at.
- `require_dry_run(environ:Mapping|None=None)->dict`: defaults true/false; rechaza flags distintos con error redactado.

Contrato de `ResumeStore(root:Path)` en `resumes.py`:

- `import_master(payload:dict, *, base_dir:Path)->str` valida maestro y copia evidencia local; devuelve master_id SHA256.
- `list_masters()->list[dict]`, `get_master(master_id)->dict` con integridad comprobada.
- `create_version(master_id:str, job:NormalizedJob, language:str, *, claim_ids:list[str]|None=None, format:str='docx')->dict`.
- `verify_version(version_id:str)->dict`, `list_versions()->list[dict]`, `export_version(version_id, destination:Path)->Path` sin sobrescribir destino existente ni escribir dentro del checkout.
- Metadata común: `version_id`, `master_id`, `sha256` (bytes exactos del documento), `language`, `format`, `vacancy_key` (lista source/board/id), `vacancy_digest`, `claim_ids`, `created_at`, `text` (representación textual exacta), `candidate_name`.
- Se puede ampliar metadata de evidencia, sin cambiar esas claves. SHA/ID hex lowercase de 64 caracteres; lenguaje es/en, formato txt/docx.

Maestro de entrada schema_version=1: `candidate` objeto con `name` texto y `contact` lista de textos; `evidence` lista `{id, path, sha256}`; `claims` lista `{id, kind, text:{es,en}, evidence_ids:[id], attested:bool}`. `kind`: experience/project/certification/education/skill. `headlines:{es,en}` opcional; no otros textos libres generados. Paths locales relativos a base_dir o absolutos, archivos regulares, sin enlaces simbólicos ni URLs; max JSON512KiB, 200 claims/100 evidence, 10MiB/evidence y100MiB total. La evidencia se copia y se verifica; no se analiza contenido activo.

Contrato de `CandidacyWorkflow(database:ApplicationDatabase, resumes:object)` en `candidacies.py` (resumes.verify_version requerido):

- `create(vacancy_id:int, resume_version_id:str, content:str|None)->int`, única candidatura por vacancy_id; reutiliza applications. None compone el borrador dentro de la transacción protegida.
- `get(id)->dict|None`, `list()->list[dict]`, `history(id)->list[dict]`.
- `edit(id, *, resume_version_id=None, content=None, vacancy_id=None, regenerate_content=False)->bool`; cambios reales crean revisión e invalidan permisos. Regeneración explícita compone dentro de la transacción, sin un content manual simultáneo.
- `review(id)->dict` con `review_digest` y snapshot completo; cambia draft→reviewed.
- `approve(id, review_digest:str)->str` authorization_id; solo digest revisado vigente, idempotente si active para ese mismo digest.
- `simulate(authorization_id:str)->dict` consume exactamente una vez; recibo con dry_run=true, auto_submit=false, submitted=false. Nunca marca applied automáticamente.
- `update_tracking(id, *, status=None, notes=None, outcome=None, next_step=None, follow_up_on=None)->bool`; fecha futura es calendario YYYY-MM-DD declarado, sin scheduler.
- `get/list` incluyen `id`, `application_id`, `vacancy_id`, `resume_version_id`, `workflow_state`, `revision`, `content`, `company`, `review_digest`, estado de tracker y próximos pasos; history conserva revisiones/eventos/autorizaciones sin borrar snapshots.
- Valida CV actual dentro de cada operación crítica; un fallo confirma invalidación antes de lanzar error, no la revierte por accidente. Compara snapshot de vacante y metadatos del CV exactamente. No acepta un callback opcional que omita verificación.
- La CLI suministra un verificador diferido: incluso un fallo al inicializar el almacén ocurre dentro del guard. Adoptar un registro legacy con contenido distinto solo se permite en saved/interested, preservando la fila/evaluación anterior y reconciliando el tracker; estados históricos posteriores con otro destino se rechazan.

## Review Focus

1. CV/evidencia/manifiesto alterado entre aprobación y simulación: invalidación persistente, sin consumo exitoso.
2. Dos procesos consumen la misma autorización: solo uno obtiene recibo; reinicio no reactiva el permiso.
3. Misma vacante mediante CLI, GUI o tracker anterior: una candidatura, historial intacto, ningún envío.
4. Cambio de empresa, ID, CV o texto, incluso cambiar y volver al contenido original: aprobación anterior inválida.
5. Documento/revisión privada dañada o ruta/symlink maliciosa: error redactado, nunca lectura/escritura arbitraria o pérdida de históricos.

### Task 1: Contratos, política y plan (principal)

Files: nuevo workflow_contracts.py; tests/test_workflow_contracts.py; este plan/diseño.

- [x] Escribir pruebas de canonicalización, identidad/digest, flags estrictos y errores sin datos privados.
- [x] Ejecutar RED: pytest tests/test_workflow_contracts.py (módulo ausente).
- [x] Implementar helpers mínimos y ejecutar GREEN + suite previa.
- [x] Commit `feat: define safe local application workflow contracts`.

### Task 2: Maestro, evidencia y versiones CV (implementador independiente)

Files: nuevos resumes.py, resume_documents.py si hace falta; tests/test_resumes.py, test_resume_documents.py. No modificar otros archivos ni Git.
Consumes contratos anteriores y NormalizedJob; produces ResumeStore API exacta arriba.

- [x] RED: maestro bilingüe incompleto/tipos/duplicados, evidencia inexistente/alterada, attested=false no se exporta, proyectos no se convierten en empleo.
- [x] GREEN: validación estricta, almacén privado content-addressed, atomicidad sin sobrescritura, hashes y trazabilidad inmutable.
- [x] RED/GREEN: versiones TXT/DOCX deterministas, adaptación por selección/orden de hechos, bytes y manifiestos/evidencia verificados, destino existente/rutas internas/symlinks rechazados.
- [x] Probar reinicio, dos procesos generando mismo CV y recuperación de publicación interrumpida; ninguna metadata válida referencia documento incompleto.
- [x] Ejecutar focused tests y devolver reporte, sin commit. Principal revisa y hace commit `feat: version evidence-backed bilingual resumes`.

### Task 3: SQLite, borradores, tracker y autorizaciones (implementador independiente)

Files: migrations.py, database.py, nuevo candidacies.py; tests/test_migrations.py y nuevos test_candidacies.py/test_authorizations.py. No modificar modelos, CLI, GUI, CV o Git.
Consumes contratos + interfaz resumes.verify_version; produces CandidacyWorkflow API exacta arriba.

- [x] RED/GREEN: esquema3, migraciones1→3 y2→3 aditivas/transaccionales, backup del origen previo, rollback y rechazo futuro; no cambiar históricos ni evaluaciones.
- [x] RED/GREEN: create dedup atómico, revisiones inmutables, historial, fechas/resultado/próximos pasos y transiciones gestionadas.
- [x] Estados tracker gestionado: saved→interested/applied/rejected/withdrawn; interested→saved/applied/rejected/withdrawn; applied→screening/interview/offer/rejected/withdrawn; screening→interview/offer/rejected/withdrawn; interview→offer/rejected/withdrawn; terminal offer/rejected/withdrawn no retroceden. Mismo estado es idempotente. Legacy sin candidacy conserva API anterior.
- [x] RED/GREEN: revisión→aprobación específica→simulación de un uso, identidad empresa/vacante/versión/hash/texto y revisión, invalidación tras cambios o integridad fallida persistida antes del error.
- [x] `ApplicationDatabase.update` valida transiciones e invalida permisos gestionados al salir de saved/interested, incluso desde CLI/GUI anteriores; nunca llama a red. Refactor privado para INSERT atómico en misma transacción en vez de conexiones anidadas.
- [x] Probar dos procesos, reinicio, abrupt exit/recovery, intentos sin revisión/digest incorrecto/consumo repetido, política insegura y applied sin envío.
- [x] Actualizar expectativas del último esquema en pruebas anteriores sin debilitar preservación; devolver focused resultados y reporte sin commits. Principal commit `feat: track reviewed drafts and single-use authorizations`.

### Task 4: Integración CLI/GUI, privacidad y documentación (principal)

Files: cli.py o nuevo workflow_cli.py, gui.py, documentación/ejemplos sintéticos y pruebas test_phase4_interfaces.py.

- [x] RED/GREEN: `resumes import/list/tailor/verify/export`, `candidacies create/list/show/edit/review/approve/simulate/update/history`, flags explícitos con errores bilingües redactados.
- [x] Importación manual explícita `vacancies import FILE` del JSON JobPosting para uso offline; no seguir URLs. Generar borrador de texto solo con datos del maestro/selecciones verificadas y datos observados de empresa/vacante.
- [x] Preservar salida de comandos/exportaciones previos y campos GUI; mostrar error de transición sin traceback con datos privados. Headless regression real con ResumeStore + CandidacyWorkflow y SQLite.
- [x] Documentar esquema3 y rollback hacia copia nueva, evidencia/atestación, formatos/límites ATS, estados, flags, datos privados, comandos y checklist manual; ajustar PLAN/README/SECURITY/PRIVACY/prompts afectados.
- [x] Commit `feat: expose private resume and candidacy workflows` y documentación atómica.

### Task 5: Revisión, validación y PR (principal)

- [x] Revisiones independientes de subsistemas y de toda la rama; corregir Important/Critical con RED→GREEN sin debilitar validaciones.
- [x] Suites completas Python3.10/3.12, pytest, pip check, compileall, CLI y preparación launchers; comprobar diff completo y privacidad.

Para cerrar la fase: publicar únicamente la rama, abrir PR a main, adjuntar URL y
confirmar seis jobs CI del HEAD final. Resultados remotos, hashes, límites y
veredicto se registran en ese PR; nunca deducir CI de los tests locales. No merge.

## Evidencia final antes de publicación

- Python3.12.14: 259 unittest y259pytest+523subtests, aprobados.
- Python3.10.22: 259 unittest, aprobados.
- pipcheck, compileall, RuffE9/F, CLIhelp, preparaciónLinux ydiffcompleto: aprobados.
- Revisiones de CV y SQLite separadas; restauración/replay, atribución y rutas
  corregidas con regresiones observadas fallar antes. Sin aserciones debilitadas.
- Revisión final y verificación acotada: 16 pruebas+19subtests y6probesindependientes,
  hallazgos cerrados. La configuración CI permanece con seis combinaciones.
- Sin validación visual de Word/Tkinter, ATS reales, envíos o despliegue.
