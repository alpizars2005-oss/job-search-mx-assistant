## Corrección preproducción R-01b y N-03

- matching_v6 reconoce country-only en condiciones de contratación aplicables al
  puesto, conservando permiso México y restricción contradictorios como evidencia.
- Añadir formatos ATS US Remote, separadores pipe/raya, alternativa ciudad-remoto,
  United States of America, Remoto y Only open to candidates.
- Separar residencia, ubicación y predicados de oficinas/clientes/beneficios/horario;
  condiciones geográficas posibles o pendientes requieren revisión, sin exclusión.
- Conservar legacy_v1/v2/v3/v4/v5; reevaluar observaciones v4/v5 sin duplicar
  vacantes/evaluaciones v6 ni reescribir los snapshots históricos.
- Sin cambios de timers, instaladores, backups, servicios, Telegram o transporte.

## Corrección preproducción N-02

- El mismo timer del reporte activa a las 14:00 y reintenta a las 14:15 en
  America/Mexico_City. Corte 14:00 y publicación idempotente sin modificaciones.
- Pruebas de lock ocupado, reintento, proceso reiniciado, día omitido, concurrencia
  e integridad byte a byte. Calendarios estático/renderizado verificados con systemd.
- No se activan servicios ni se añade un scheduler residente.

## Corrección preproducción R-01

- matching_v4 interpreta etiquetas completas de ubicación exclusiva, incluidas
  variantes US only, US-based y listas US & Canada; conserva evidencia y offsets.
- Alternativas explícitas México evitan inferir exclusividad de una ubicación US
  sin only; las restricciones excluyentes explícitas siguen teniendo precedencia.
- Las observaciones v3 se reevalúan bajo v4 sin reescribir historial ni snapshots.
- Sin cambios en despliegue, fuentes activas, candidaturas o transporte externo.

## Fase 6B — preparación propuesta, dependiente del hardening

- Reportes diarios 14:00 México JSON/Markdown privados, catchup/idempotencia y SHA.
- Separación de estados: descubierto/evaluado/preparado/aprobado/simulado/manual
  applied; cero envíos reales confirmados sin recibos externos.
- Bundles SQLite+CV+config+reportes, verificación/restore nuevo y retención dry-run.
- Mutex también en comandos lectores que migran y durante la ventana GUI.
- Releases offline SHA/wheel fijos, preflight Debian 12/Python 3.11, systemd oneshot/timers.
- Entorno administrativo mínimo; sin despliegue, puertos, credenciales o mensajería.
- Work oficial investigado, fallback local completo; entrega no configurada/verificada.

## Fase 6 — hardening propuesto

- matching_v3: restricciones geográficas, contradicciones y contexto de rol conservador.
- Control local separado de errores ATS; Retry-After extremo suspendido sin truncación.
- Almacenamiento privado POSIX compartido y validación de archivos/links/propietario.
- Telegram retirado; esquema5 aditivo conserva historia y bloquea nuevas escrituras.
- Recuperación de fuentes auditada, revisión tras restore y health activo/abandonado.
- Claude bloquea flags/contexto debug; CI Windows/Ubuntu incorpora Python 3.11.
- Sin despliegue, revisión Claude real, mensajes ni envíos de candidaturas.

# Changelog

## Unreleased

- Agregar maestros ES/EN con evidencia/atestación, CV TXT/DOCX deterministas,
  hashes, trazabilidad y almacenamiento privado fuera del checkout.
- Extender SQLite a esquema 3 con migraciones seguras, revisiones inmutables,
  tracker gestionado y autorizaciones exactas de un uso para simulación local.
- Agregar CLI de documentos/borradores, importación manual offline de vacantes y
  errores redactados de transiciones en la CLI/GUI anteriores.
- Conservar historial al cambiar destino y revocar capacidades durante restore;
  documentar backup conjunto, formatos ATS, política y checklist manual.

- Agregar esquema SQLite 2, migración transaccional con backup previo, validación
  de versiones, deduplicación persistente y snapshots de evaluaciones.
- Evaluar elegibilidad antes de compatibilidad mediante `matching_v2`, seis
  clasificaciones y evidencia reproducible; preservar históricos `legacy_v1`.
- Conectar vacantes normalizadas mediante `discover --save` y comandos locales
  `vacancies list/evaluate`; agregar backup/restauración sin sobrescritura.
- Conservar hechos opcionales del perfil al editar desde GUI y mostrar explicaciones
  bilingües; agregar pruebas offline de migración, concurrencia e interfaces.
- Corregir el alcance de requisitos y sus menciones repetidas, permisos/exclusiones
  de México, autorizaciones por país, experiencia específica y predicados negativos.

- Agregar descubrimiento opt-in de Greenhouse, Lever y Ashby con normalización,
  procedencia y deduplicación en memoria, sin cambios a SQLite o perfiles.
- Acotar GET por host/ruta, timeout, tamaño, solicitudes, reintentos, backoff con
  jitter, Retry-After, paginación y pausa tras errores consecutivos.
- Agregar configuración de fuentes JSON deshabilitada por defecto, comando
  `discover`, reportes parciales y errores de configuración en español/inglés.
- Incorporar las dos pruebas CSV omitidas al descubrimiento unittest de CI y
  agregar pruebas sintéticas de fuentes sin servicios externos.
- Documentar proveedores diferidos y consultas reales bloqueadas por red Cloud.


- Validate imported profile structures and field types before use.
- Tolerate malformed settings, including invalid UTF-8, without rewriting the original file.
- Add 13 regression test methods for invalid inputs, valid-profile compatibility and file preservation.
- Explain the loader fallback and the evaluator's text-matching limitations in both user guides.

## 1.0.0 - 2026-07-22

- Added bilingual English/Spanish desktop interface.
- Added cross-platform CLI.
- Added profile-driven job-fit evaluator.
- Added local SQLite application tracker.
- Added CSV and JSON export.
- Added Windows and Linux install, run, and build scripts.
- Added privacy-first local data storage.
- Added automated tests and GitHub Actions CI.
