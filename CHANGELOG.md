# Changelog

## Unreleased

- Añadir Python 3.11 a CI de la rama histórica de fuentes en Windows y Ubuntu.
  Los pushes a esa rama comprueban el commit exacto, con las mismas pruebas
  y smokes existentes.

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
