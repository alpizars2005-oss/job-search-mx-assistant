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
