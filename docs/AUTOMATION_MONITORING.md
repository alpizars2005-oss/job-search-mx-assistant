# Automatización, recuperación y monitoreo

Fase5 integrada en PR #10, base `cfa6a4d974ce129a2bc8aeeb4ee4d53b6afc44f7`.
Hardening de Fase 6 propuesto, pendiente de revisión/integración. No despliegue real.

## Operación

```bash
export JOB_SEARCH_ASSISTANT_HOME=/ruta/privada/jobsearch
export DRY_RUN=true
export AUTO_SUBMIT=false
jobsearch init --language es
jobsearch profile import /ruta/privada/profile.json
jobsearch automation run --config /ruta/privada/sources.json --budget-seconds 120
jobsearch automation runs --limit 20
jobsearch automation show ID
jobsearch automation health --max-age-seconds 86400
jobsearch automation sources
```

Perfiles JSON, CLI/Tkinter y exportaciones anteriores se conservan. El perfil
operativo debe ser válido, regular y no superar 512 KiB: nunca se sustituye por
hechos predeterminados. La lectura histórica de perfiles conserva su compatibilidad.
Sin config no hay fuentes activas ni HTTP. Un run vacío exitoso no prueba red ATS.
Producción debe fijar un commit revisado; no usar launchers con autoactualización.

Presupuesto 0.05–86400 s, default 120. Incluye esperas, HTTP y procesamiento; el cierre
transaccional y un disco bloqueado pueden añadir tiempo. SQLite operativo espera
hasta 100 ms por escritor. HTTP usa worker spawn terminable y watchdog; si un worker
sobrevive terminate/kill se informa worker_cleanup_failed, sin afirmar su cierre.

## Persistencia y límites

Mutex OS `automation.lock` cubre migración, recuperación y búsqueda. No borrar ni
reemplazar el lockfile: el kernel libera flock/msvcrt al morir el proceso. El próximo
run marca abandonados como interrupted y conserva commits previos. No coordina
hosts/clones/NFS ni discover independiente; no invocarlos para evadir cuotas.
SIGINT/SIGTERM solicitan interrupción. Cada observación confirma vacante, evaluación
y hallazgo en una transacción. Un proveedor fallido no pierde resultados de otros.
No se generan hechos de CV, borradores, aprobaciones ni envíos automáticamente.

Esquema SQLite 5 aditivo desde 1–4, con backup consistente previo y rollback
transaccional. Las tablas de automatización conservan snapshots y referencias
inmutables. `matching_v4` se aplica a evaluaciones nuevas, conservando v3/v2/legacy_v1.
Cambio solo en retrieved_at reutiliza evaluación; cambios semánticos revocan
aprobaciones exactas mediante el guard previo de Fase4.

Cancelación, deadline, fallo local de worker y fuentes no intentadas no aumentan
rachas de error ATS. Un429/5xx real recibido sí se registra aunque luego se cancele.
Una respuesta completada guarda metadatos antes de atender cancelación; no se
procesa otro JSON ni reintento después. Restricciones nunca recibidas son desconocidas.

Estado HTTP v2 importa v1 y conserva UTC, pausas, backoff y Retry-After entre runs.
La reserva previa al GET protege un reinicio sin inventar un fallo. Plazos válidos
más allá del horizonte configurable (default 86400 s) crean suspensión manual durable.
Decimales enormes se conservan como texto, sin truncar/convertir a infinito; un
plazo no representable no admite desbloqueo automático. HTTP-date hasta 9999 se
conserva. Validaciones rechazan estados con un deadline falsificado más temprano.

## Recuperación auditada de fuentes

Inspeccionar `automation sources`, conservar state_digest y revisar evidencia.
`automation resume-source PROVIDER --state-digest SHA256 --reason-code CODE`
solo puede liberar una suspensión/pausa después de toda restricción conocida.
`automation review-restored-sources --state-digest SHA256 --reason-code CODE`
registra revisión explícita tras restauración, con las mismas restricciones.
Ambos requieren política segura, mutex y transacción con evento inmutable en
operational_control_events. Un digest obsoleto falla sin mutación.

Restore revoca capacidades CV y establece source_review_required=1. No habilitar
fuentes antes de revisar: un backup antiguo puede omitir cooldowns posteriores.
Esperar los plazos conocidos no demuestra que no existan restricciones perdidas;
consultar evidencia reciente/proveedor y, si no existe, mantener fuentes apagadas.
Nunca borrar estado, adelantar el reloj o editar SQLite para eludir un Retry-After.
La ejecución sin fuentes habilitadas sigue disponible durante revisión.

## Salud, logs y salidas

Stdout: JSON; stderr: eventos redactados con códigos/fechas/IDs/contadores. Sin CV,
perfiles, contacto, títulos/URLs, respuestas remotas o excepciones privadas. Health
abre SQLite solo lectura, sin crear/migrar/endurecer archivos. Distingue lock activo
legítimo, running abandonado, antigüedad, último éxito y degradación de proveedores.
Un diagnóstico no valida conectividad real ni permite robar un lock.

| Salida | Interpretación |
| --- | --- |
|0|Run completo o lectura correcta|
|1|Resultados parciales o health degradado|
|2|Configuración, política o almacenamiento inválidos|
|3|Otra ejecución mantiene mutex|
|4|Presupuesto agotado|
|130|Interrupción solicitada|

No convertir fallos en éxito systemd. Las pausas conservan resultados válidos pero
requieren diagnóstico, no un bucle de reintentos inmediato.

## Telegram retirado y Claude preparado

No existen telegram.py/notifications.py, --notify, configuración o productores.
Variables heredadas no tienen efecto. Esquema 5 preserva outbox/delivery/health y
notifications_json históricos; triggers bloquean escrituras incluso de código
antiguo. Nuevos runs no crean eventos. Restore no reinterpreta filas históricas.
Los tests del transporte eliminado se sustituyen por pruebas de migración,
preservación byte a byte y ausencia de red; no constituyen una activación futura.

Claude continúa manual/desactivado. Flags debug de variables/secretos/contexto
runner se rechazan antes de leer el diff, y no se solicita la credencial del modelo
antes de validar. Aun sin debug, upstream puede imprimir el prompt: revisión humana
del diff publicable sigue siendo obligatoria. No hubo llamada real a Claude.
Ver [evidencia y límites](CLAUDE_REVIEW.md).

## Almacenamiento, restauración y rollback

POSIX: directorios gestionados 0700 y archivos 0600, incluido SQLite/WAL/SHM y
backups, independientemente de umask. Aperturas rechazan links inseguros, objetos
no regulares y propietarios ajenos. No se cambian imports externos ni directorios
generales. Windows necesita ACL privadas independientes; hashes no cifran datos.
No se afirma resistencia a un administrador o al mismoUID que controle el almacén.

```bash
jobsearch database backup --source /datos/applications.sqlite3 --output /backup/nuevo.sqlite3
jobsearch database restore --source /backup/nuevo.sqlite3 --output /recuperacion/nuevo.sqlite3
```

Estos comandos cubren SQLite; conservar además CV/evidencias/configuración como
conjunto. Destino siempre nuevo, nunca sobre una base abierta. Restore conserva
versión original, revoca aprobaciones activas y exige revisión de fuentes. Un backup4
recibe protección de historial retirado antes de publicarse. Migrará al abrirse.
Rollback a código anterior requiere backup de esquema compatible previo a migración;
no bajar el marcador ni abrir esquema 5 con código 4. Preservar cambios posteriores
para reconciliación manual. Un rollback puede perderlos si solo existe copia antigua.

## Verificación y pendiente de PizzaLab

Datos sintéticos, unittest+pytest+dependencias+compilación y matriz 8 Windows/Ubuntu,
Python 3.10/3.11/3.12/3.13. Resultados reales del SHA final se registran en el PR.
No afirmar pruebas Windows locales, GUI visual, Claude, Debian 12/LXC o producción
por haber pasado pruebas headless. Codex Cloud no es alojamiento permanente.

- [ ] Integrar PRs tras revisión; configurar protección de main por el propietario.
- [ ] Verificar LXC, usuario, ACL, DNS/TLS/egress y acceso ATS permitido.
- [ ] Validar perfil/hechos/evidencias y fuentes sin asumir elegibilidad México.
- [ ] Probar interrupción/reinicio/restore en copia sintética y respetar restricciones.
- [ ] Validar recursos, backup conjunto, rollback y timers antes del piloto real.


## Preparación dependiente B

Reportes y backups completos están preparados en PR separado sobre A; no activos
ni integrados. Comandos/temporalidad en [DAILY_REPORTS](DAILY_REPORTS.md), recuperación
conjunto/retención en [STORAGE_RECOVERY](STORAGE_RECOVERY.md), instalación y checklist
real en [DEPLOYMENT](DEPLOYMENT.md). GUI y lectores CLI que inicializan/migran ahora
comparten mutex; cerrar la ventana antes de programar el mismo home.
