# Phase 6 hardening Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans or dispatching-parallel-agents with disjoint ownership; tests RED→GREEN.

**Goal:** cerrar hallazgos comprobados y retirar Telegram antes de preparar operación.
**Architecture:** núcleo actual con límites comunes, semántica versionada y migración
aditiva; infraestructura/reportes van en PR apilado independiente.
**Tech Stack:** Python3.10–3.13, SQLite, stdlib, ocho jobs Windows/Ubuntu.
**Spec:** `docs/superpowers/specs/2026-11-04-phase6-hardening-design.md`.

## Global Constraints

- DRY_RUN=true/AUTO_SUBMIT=false; sin envíos, Telegram, modelos ni despliegue real.
- Datos sintéticos; preservar JSON/CLI/Tkinter/CSV/SQLite/CV/autorizaciones históricas.
- Sin merges, borrados de datos reales o cambios remotos de protección/permisos.
- Nuevas instrucciones autorizan ramas apiladas con dependencias explícitas.

## Review Focus

- Permiso México relativo a otro rol no habilita esta vacante; negaciones no excluyen.
- Deadline tras recibir respuesta no inventa fallo ni pierde cooldown externo.
- Links/owner/umask000 y sidecars evaden un chmod aplicado solo al principal.
- Código anterior o restauración no puede reactivar Telegram/autorizaciones/cuotas.
- Health activo con lock legítimo frente a running abandonado sin lock.

### Task 1 — M01, motor de elegibilidad (agente, archivos aislados)

Files: eligibility.py, matching.py, tests/test_eligibility.py,
tests/test_matching.py y nuevo test_geographic_hardening.py.
Interface: evaluate_match conserva firma; exporta ALGORITHM_VERSION='matching_v3'.
Los resultados históricos guardados no se modifican. Root integra constante en store.

- [ ] Reproducir los seis ejemplos Claude y controles válidos/negaciones/roles.
- [ ] RED: exclusión→ineligible, contradicción→insufficient_information, nunca high.
- [ ] GREEN: alcance contextual conservador, evidencia original y versión nueva.
- [ ] Suites focales/completas, informe, congelar archivos; commit por root.

### Task 2 — M02/L01/I05, control y fuentes (agente)

Files: sources/http.py, sources/discovery.py, runtime_control.py, automation.py,
tests de esos módulos y test_source_hardening.py. No editar automation_store.py.
Interface: status not_attempted/interrupted para reportes de control local;
provider failures excluyen control local; callback HTTP ofrece payload versionado
documentado antes de integración. Conserva import de payload v1. ALGORITHM_VERSION
no pertenece a este módulo.

- [ ] RED: cancelar antes/durante request, 200+deadline, entre proveedores, cinco
  interrupciones; preservación de 429/5xx reales y Retry-After recibido.
- [ ] GREEN: reservas sin fallo ficticio, salida local separada y no seguir fuentes.
- [ ] RED/GREEN extremos: plazo grande/overflow→suspensión manual durable,
  no acortar válido; definir formato/control de desbloqueo seguro con root.
- [ ] I05: si worker no termina tras kill, error claro y no close sobre proceso vivo.
- [ ] Verificar invariantes anteriores, informe/API exacta, congelar; commit root.

### Task 3 — M03, límite privado (root)

Files: nuevo private_storage.py; config/database/migrations/resumes/exporters/
workflow_cli/CLI y lectura SQLite operacional según callers concretos.
Prepatch: investigación independiente read-only más trazado propio, reconciliar.

- [ ] RED umask022/000, lectura/escritura/actualización/reinicio, SQLite sidecars,
  backup/restore, symlink/owner/hardlink, preserve malformed bytes legítimos.
- [ ] GREEN utilidades shared para paths, dirs, fd seguros, escritura atómica y
  SQLite privado. No endurecer imports externos/ancestros generales ajenos.
- [ ] Pruebas de bypass/regresión independientes; sintaxis, triggers, controles
  legítimos, suites y CI; distinguir POSIX demostrado y ACL Windows pendientes.

### Task 4 — Retirada Telegram y estado operacional (root)

Files: automation_store/cli/schema/migrations y tests/interfaces. Retirar telegram.py
y notifications.py de runtime; preservar DDL histórico en módulo de esquema legacy.

- [ ] RED: sin --notify/credenciales/conexiones/eventos, esquema4 histórico intacto.
- [ ] GREEN migración5 aditiva/backup, tablas retiradas read-only y productores fuera;
  actualizar pruebas anteriores manteniendo aserciones históricas en fixtures legacy.
- [ ] Integrar API Task2 y versión Task1; sin falsos source_error ni cuotas borradas.
- [ ] L04 health actual/abandonado/recuperado; L01 recuperación auditada tras plazo;
  I03 restore conserva restricciones y exige revisión cuando falta estado reciente.
- [ ] Suites y commit por unidad lógica.

### Task 5 — CI, Claude, docs y revisión (root + investigación read-only)

- [ ] L02 documentos oficiales actuales, cubrir runner.debug/flags/env; fail-closed
  verificable, limitación de logs upstream explícita, sin invocar Claude.
- [ ] L03 ampliar matriz a 3.10/3.11/3.12/3.13 ambos OS, sin quitar combinaciones.
- [ ] Actualizar AGENTS/PLAN/README/SECURITY/PRIVACY/CHANGELOG y evidencias.
- [ ] Final unittest/pytest/pip/compile y revisión independiente de rama/seguridad.
- [ ] PR hardening main, attach, CI8/8 real; no merge. Preparar rama apilada B con
  dependencia visible, conservando estado HARDENING PENDIENTE mientras no integrado.
