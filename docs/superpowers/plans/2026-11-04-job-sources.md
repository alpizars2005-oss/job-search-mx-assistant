# Job Sources Implementation Plan

> **For agentic workers:** usar superpowers:executing-plans, con pruebas primero y una revisión independiente de la rama completa al final.

**Goal:** completar la Fase 2: descubrir vacantes públicas de tres ATS, sin persistencia ni envíos.
**Architecture:** cliente HTTP GET compartido con presupuestos por proveedor; adaptadores puros para normalizar; orquestador en memoria y comando CLI explícito. Sin modificar GUI, perfiles JSON, matching ni SQLite.
**Tech Stack:** Python 3.10+, biblioteca estándar; unittest/pytest existentes.
**Spec:** `PLAN.md`, sección Fase 2, y misión de Fase 2 autorizada en este chat.

## Global Constraints

- Rama `codex/phase-2-job-sources` desde `main` actualizado, base `b69a6fedc3a3e83a794f7d3e1078332c792d983e`.
- Sin dependencias de runtime nuevas, scraping, POST, credenciales o servicios.
- Fuentes deshabilitadas por defecto; configuración de fuentes JSON separada del perfil; YAML sigue como referencia documental.
- 20 solicitudes por proveedor/ejecución incluyendo páginas y reintentos; timeout 15 s, 3 reintentos, backoff exponencial con jitter hasta 30 s y breaker a 5 errores consecutivos.
- Presupuesto adicional de espera 30 s/proveedor/ejecución, pausa 300 s, intervalo mínimo 1 s y cuerpo máximo 5 MiB; todos configurables y validados.
- Nunca reducir Retry-After para encajarlo: posponer si no cabe. Ninguna redirección automática.
- La elegibilidad regional permanece desconocida; texto de vacantes nunca ejecutado o renderizado como HTML activo.
- Pruebas sintéticas, sin servicios externos en CI. Una fase, un PR sin merge.

## Review Focus

- Una redirección o URL devuelta no debe permitir contactar un host ajeno al ATS.
- Varios tableros del mismo proveedor deben compartir cuota y pausa, sin multiplicar reintentos.
- Una página Lever con registros inválidos debe avanzar por cantidad recibida, sin duplicar o perder el límite.
- Campos ausentes, fechas de actualización y palabras Remote/AMER no deben inventar publicación ni elegibilidad.
- Resultados truncados o parcialmente inválidos deben distinguirse de una consulta completa/vacía.

## Diseño y alternativas

Se elige urllib con transporte inyectable y rechazo total de redirects; una librería HTTP añadiría una dependencia sin beneficio necesario. Se agrega un paquete `jobsearch_assistant.sources`, separado de los modelos históricos para no cambiar el contrato del tracker. La CLI entrega JSON con datos y reportes; no integra el score existente por sus limitaciones auditadas. No se usará navegador ni cargador YAML.

Los límites son locales del cliente, no promesas de cuotas oficiales. La documentación oficial describe GET públicos para Greenhouse, Lever y Ashby; las condiciones generales exigen uso no abusivo y no garantizan redistribución universal. La configuración explícita por tablero mantiene la decisión de uso en manos del operador.

## Task 1: Contratos y transporte seguro

**Files:** crear `src/jobsearch_assistant/sources/{__init__,models,http}.py`, `tests/test_source_http.py`; convertir `tests/test_exporters.py` a unittest y nombrar explícitamente su cobertura en CI.
**Interfaces:** `SourceConfig(provider, board, company, enabled=False)`, `RequestPolicy`, `HttpResponse`, `SafeHttpClient.get_json(provider, url, validator)`; transporte callable `(url, timeout, max_bytes) -> HttpResponse`. `SourceError.code` no revela contenido externo.

- [ ] Escribir pruebas de URL/host/path, respuestas JSON/HTML/tamaño, redirects, timeout/429/5xx, Retry-After numérico/fecha, jitter, cuotas compartidas, espera y breaker/cooldown.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/test_source_http.py -q`: esperar fallo por módulo ausente.
- [ ] Implementar contratos y transporte GET con dependencias de reloj/espera/aleatoriedad inyectables; nunca desactivar proxy o TLS.
- [ ] Ejecutar pruebas enfocadas y suite completa: esperar éxito; commit `feat: add bounded read-only source transport`.

## Task 2: Adaptadores, normalización y deduplicación

**Files:** crear `sources/{adapters,discovery}.py`, `tests/test_job_sources.py`.
**Interfaces:** `NormalizedJob` contiene campos requeridos, tablero/procedencia y evidencia sin interpretar. `DiscoveryEngine.run(configs) -> DiscoveryResult`, con jobs y reportes por tablero. Identidad `(source, source_board, source_job_id)`.

- [ ] Escribir fixtures sintéticas para cada ATS: válido/incompleto/vacío/shape inválido, URLs maliciosas, ubicaciones/fechas desconocidas, evidencia/procedencia, páginas repetidas y límite de paginación.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/test_job_sources.py -q`: esperar fallo por API ausente.
- [ ] Implementar endpoints construidos localmente y validación de URLs de ofertas sin seguirlas; Greenhouse/Ashby una respuesta, Lever skip/limit acotados.
- [ ] Probar independencia de proveedores y cuota compartida entre tableros; no emitir IDs artificiales cuando falta identidad estable.
- [ ] Ejecutar pruebas enfocadas y suite completa: esperar éxito; commit `feat: discover and normalize public ATS postings`.

## Task 3: Configuración, CLI y documentación

**Files:** crear `sources/config.py`, `tests/test_discovery_cli.py`, `examples/sources.example.json`, `docs/JOB_SOURCES.md`; modificar CLI, PLAN, README, arquitectura, SECURITY y CHANGELOG donde corresponda.
**Interfaces:** `load_source_config(path) -> (list[SourceConfig], RequestPolicy)` con límites de tamaño/estructura y rechazo de campos desconocidos. `jobsearch discover [--config PATH] [--language es|en]`: JSON en stdout; 0 completo/deshabilitado, 1 parcial/error, 2 configuración inválida.

- [ ] Escribir pruebas de defaults sin red, flags/tipos maliciosos, errores redactados/bilingües, serialización y compatibilidad con comandos previos.
- [ ] Ejecutar prueba enfocada: esperar fallo por comando/módulo ausente; implementar integración mínima sin SQLite.
- [ ] Documentar fuentes diferidas, condiciones oficiales y límites; intentar lecturas reales solo por red permitida y registrar resultados honestos.
- [ ] Ejecutar suite, compilación, pip check, ayuda, configuración deshabilitada y smoke Linux; revisar diff y commits atómicos.
- [ ] Revisión independiente de rama, correcciones con regresiones si procede, PR a main y detenerse antes de Fase 3.
