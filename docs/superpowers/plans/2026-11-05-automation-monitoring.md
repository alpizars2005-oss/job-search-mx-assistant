# Automation and monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** ejecutar búsquedas una vez con recuperación, historial y monitoreo privado.
**Architecture:** núcleo serial, mutex OS, HTTP aislado y SQLite transaccional.
Notificaciones opt-in mediante outbox y revisión Claude preparada sin credenciales.
**Tech Stack:** Python 3.10+, stdlib, SQLite; seis jobs CI existentes.
**Spec:** `docs/superpowers/specs/2026-11-05-automation-monitoring-design.md`.

## Global Constraints

- DRY_RUN=true/AUTO_SUBMIT=false obligatorios; ningún envío ni candidatura automática.
- Conservar CLI/Tkinter, ES/EN, JSON, perfiles y snapshots históricos.
- No servicios, dependencias de runtime, despliegue ni Fase 6.
- Datos sintéticos y pruebas offline; secretos nunca se imprimen ni commitean.

## Review Focus

- Crash entre solicitud y cooldown: no eludir límites persistentes al reiniciar.
- Respuesta lenta que nunca termina: subproceso debe poder terminarse.
- Cambio solo de retrieved_at: no multiplicar evaluaciones/avisos.
- Cambios de perfil y vacante con candidatura aprobada: preservar e invalidar exactamente.
- Telegram acepta pero no llega respuesta: estado ambiguo no reenvía al reiniciar.

### Task 1: límites de ejecución y transporte (dominio independiente A)

Files: crear `runtime_control.py`, modificar `sources/http.py`, tests
`test_runtime_control.py`, `test_source_runtime.py`.
Interfaces: `RunControl(seconds, cancelled=None, monotonic=time.monotonic)` con
`check()`, `remaining()`, `sleep(delay)`; errores SourceError `run_cancelled`/
`run_deadline`. `RunLock(path)` context manager lanza WorkflowError `run_locked`.
`BoundedTransport(control, transport=None)` compatible con UrllibTransport.
SafeHttpClient acepta `control=None`, `state_callback=None`; métodos
`export_state()->dict` y `import_state(payload)` para failures y tiempos UTC.
Callback recibe export_state después de reservas/red/cooldown; sin contenido HTTP.

- [ ] RED: lock entre dos procesos, recuperación tras kill, cancelación, respuesta
  lenta, Retry-After importado, cuota previa a red y deadline en backoff.
- [ ] GREEN: implementar APIs, conservar cliente anterior sin opciones nuevas.
- [ ] Verificar tests nuevos y suite; entregar informe y commit atómico por root.

### Task 2: outbox Telegram (dominio independiente B)

Files: `notifications.py`, `telegram.py`, `test_notifications.py`, `test_telegram.py`.
Interfaces: `create_notification_tables(connection)` dentro de migración4.
`queue_event(connection,key,kind,*,entity_id=None,count=1,language='es')->bool`.
Kinds priority/review_pending/eligibility_pending/source_error/recovered/run_summary.
`TelegramConfig` y `load_telegram_config(environ=None)`; env JOBSEARCH_TELEGRAM_*
ENABLED/TOKEN/CHAT_ID. `NotificationDispatcher(database,config,*,transport=None,
control=None).drain(authorized=False)->dict` con métricas redactadas. No acceso al
CV, perfil, títulos/URLs de vacantes; locks del dispatcher seguros entre procesos.

- [ ] RED: sin token/permiso, dedup/reinicio/concurrencia, 429 Retry-After, 5xx,
  transporte ambiguo, límites, redirección, texto privado nunca aparece.
- [ ] GREEN: outbox persistente, presupuesto, default disabled y no envío en tests.
- [ ] Verificar, informe y commit por root; root incorpora migración4.

### Task 3: Claude preparado (dominio independiente C)

Files: workflow manual, `scripts/prepare_claude_review.py`, prompts de auditoría,
`docs/CLAUDE_REVIEW.md`, pruebas del preparador.
Interfaces: sin dependencias de runtime; nada se invoca automáticamente.

- [ ] Investigar acción oficial, inputs, permisos, amenazas y SHA actual.
- [ ] RED: selección de PR/SHA, rechazo fork y cambio de SHA, diff excesivo y
  código/mensajes maliciosos; probar efectos del preparador sin red real.
- [ ] GREEN: workflow opt-in manual protegido, sin ejecutar árbol del PR ni
  herramientas de modificación, informe ligado a SHA; ausencia de secreto explícita.
- [ ] Verificar sintaxis/comportamiento; documentar no ejecución real de Claude.

### Task 4: persistencia y orquestación (root)

Files: `automation_store.py`, `automation.py`, migraciones/database internos,
`test_automation_store.py`, `test_automation.py`, `test_automation_migrations.py`.
Interfaces: `AutomationStore(database)` start/recover/observe/finish/states/history;
`AutomationRunner(database,profile,configs,policy,*,control,client=None,language='es')`
con `run()->dict` redactado. APIs exactas se fijan en este módulo antes de CLI.

- [ ] RED: schema3 preservado/rollback/backup, operación atómica, repetición,
  changed/profile-only/new, recuperación y ninguna modificación de candidaturas.
- [ ] GREEN: esquema4 aditivo, reutilizar lógica de upsert/evaluation dentro de una
  conexión común; findings+outbox en la misma transacción.
- [ ] RED/GREEN: fallos parciales/paginación, fuente persistida pausada, deadline,
  cancelación, reinicio, no datos privados en resúmenes y selección habilitada.
- [ ] Ejecutar suites completas y commit.

### Task 5: CLI y entrega (root)

Files: `automation_cli.py`, CLI parser/dispatch, docs operativas, PLAN/README/
SECURITY/PRIVACY/ARCHITECTURE, CI y pruebas de interfaces.

- [ ] RED/GREEN: `automation run/health/runs/show`; lock antes de migración,
  perfil estricto (no fallback silencioso), presupuesto validado, señales,
  códigos 0 completo/1 parcial/2 configuración/3 lock/4 deadline/130 interrupción.
- [ ] Integrar notificaciones explícitas, scan de candidaturas por ID/revisión;
  ninguna generación/aprobación automática. Logs JSON allowlist.
- [ ] Documentar comandos, seguridad/rollback/checklist y requisitos futuros de
  PizzaLab, sin crear/instalar timers de Fase 6.
- [ ] Suite unittest/pytest/pip check/compileall y smoke CLI/GUI existente.
- [ ] Revisión independiente de rama, corregir hallazgos verificables; commits.
- [ ] PR a main y artefacto adjunto, verificar seis jobs del HEAD final, no fusionar.
