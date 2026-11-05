# Hardening de Fase 6 — evidencia y límites

Base: PR #10 integrado, main `cfa6a4d974ce129a2bc8aeeb4ee4d53b6afc44f7`, CI74
satisfactorio. Esta entrega propone cambios; no afirma integración o despliegue.
Los hallazgos suministrados de Claude se reprodujeron con datos sintéticos propios.
No se invocó a Claude para esta implementación.

| Hallazgo | Reproducción y cambio | Evidencia |
| --- | --- | --- |
|M-01|Permiso México más exclusividadEEUU antes high_priority95; ahora contradicción/inelegibilidad conservadora por contexto, sin habilitar otro rol|test_geographic_hardening, test_matching; matching_v3, históricos intactos|
|M-02|Cancelar tras200 antes penalizaba también proveedor sin consultar|test_source_hardening, test_automation; control local neutral,429/5xx reales conservados|
|M-03|umask022 antes home0755/JSON/SQLite0644|test_private_storage; directorios0700/archivos0600, tipos/owner/links/auxiliares|
|M-04|Runtime Telegram y productores activos aunque opt-in|test_telegram_retirement, test_phase5_interfaces; módulos/flag eliminados, historia inalterada y triggers de retirada|
|L-01|Retry-After enorme requiere preservar restricción sin overflow|test_source_hardening/source_recovery; texto decimal durable, suspensión manual, digest/auditoría, restore en cuarentena|
|L-02|30 casos debug adicionales permitían preparar diff|test_claude_review; secrets/vars/runner.debug rechazados antes de preparación|
|L-03|Python3.11 faltaba|CI define Windows/Ubuntu×3.10/3.11/3.12/3.13; confirmar8/8 en SHA delPR|
|L-04|running legítimo se diagnosticaba mal|test_operational_health; activo/demorado/abandonado/antiguo/proveedor degradado separados|
|L-05|Crecimiento sin política explícita|Entrega B separada: inventario/simulación, sin borrados automáticos|
|I-03/I-05|Restore antiguo puede perder límites; worker vivo no admiteclose|Revisión explícita tras restore; no ignorar plazos conocidos; worker_cleanup_failed si sobrevivekill|

## Revisión del límite privado

Se realizó investigación independiente previa al parche y revisión independiente
read-only de un candidato. Esta detectó dos regresiones: restore alteraba permisos
del origen externo y perfiles válidos de más512KiB podían cargar valores por defecto.
Tres casos RED las reprodujeron; el autor corrigió ambos límites y pasó114 pruebas
focales con188subtests. No se atribuye una segunda revisión a ese revisor.
No se publican artefactos temporales de seguridad ni datos personales en Git.

Aperturas SQLite distinguen almacenamiento gestionado e imports externos de solo
lectura. La protección POSIX se verificó con umask000/022/777, WAL/SHM existentes,
backup/restore, symlinks/hardlinks y rechazo de owner simulado. No se realizó ataque
crossUID real ni validación de ACL nativa Windows en Cloud. Un administrador o el
mismoUID que controle todo el almacén sigue pudiendo falsificarlo; no es cifrado.

## Pruebas y validación

Los resultados finales locales, revisión funcional y CI remoto de cada SHA se
registran en el PR. Las pruebas no dependen de servicios externos. Se conservaron
los launchers y ambas suites; los tests del transporte retirado fueron sustituidos
por controles de ausencia/migración/historial, no por una simulación de entrega.
No afirmar que un run sin fuentes demuestra conectividad, ni que unit tests
validan Debian12/LXC/systemd en producción, GUI visual, Telegram, Claude o Work.

Para rollback: preservar backup previo al esquema5 y documentos/config coherentes;
restaurar a destino nuevo con código compatible, nunca bajar el marcador. Restore
revoca aprobaciones y mantiene revisión de fuentes. No eliminar historial real,
locks, cuotas ni restricciones para forzar recuperación.


## Corrección preproducción R-01 — 2026-11-05

HEAD comprobado antes del cambio: #11 en 6b915569a0224613680bc4f3354d36814104b4e1;
#12 en 50a2b157748276a555a3a28a06580b3979a816b5, ambos abiertos y sin integrar.
La auditoría suministrada de Claude se comprobó con datos sintéticos propios.

Causa raíz: el fullmatch de ubicación no aceptaba only dentro de paréntesis,
US-based, listas de países ni el país único del ATS. La segmentación por punto y
coma perdía el contexto de `Remote; US-based`. Evaluar cada ubicación por separado
también convertía una lista que incluía México en una exclusión falsa.

Se reconstruye cada campo de ubicación conservando sus spans/offsets/procedencia;
una gramática acotada reconoce esas etiquetas. Las alternativas México suprimen
solo exclusividad inferida; only y restricciones del cuerpo siguen excluyendo o
produciendo contradicción. No se convierte una mención incidental US en exclusión
ni una ubicación México en permiso de contratación. Parser del cuerpo preservado.

RED: 31 fallos de subTest. Los siete ejemplos R-01 se probaron como JobPosting y
NormalizedJob, con/sin permiso México, más controles positivos y contradicciones.
La regresión de caché conserva el snapshot matching_v3 y genera una evaluación
matching_v4 independiente al observar de nuevo el mismo contenido. Esta versión
nueva evita reutilizar una prioridad alta v3 afectada; no migra ni reinterpreta
históricos automáticamente. Resultados GREEN/suites/CI del SHA final en el PR.

Checklist manual: revisar evidencia de exclusión y contradicción de las siete
etiquetas, confirmar listas US/México permitidas sin exclusividad explícita y
verificar nueva evaluación v4 junto al histórico v3. No activar fuentes o servicios.

La revisión interna independiente de0a3b96c encontró una regresión adicional:
dos etiquetas completas dentro de un mismo campo (US; Canadá) perdían su exclusión.
Se reprodujeron seis subtests RED en ambos modelos; se conserva ahora cada span
reconocido cuando el campo reúne varias etiquetas y no incluye alternativa México.
La revisión corresponde a ese SHA, no constituye una nueva revisión de Claude.
