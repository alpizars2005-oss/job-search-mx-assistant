# Fase 5: ejecución única, recuperación y monitoreo

## Alcance y decisiones

Misión autorizada después de PR #9 integrado en main `a30d036`, CI 71 aprobado.
Python 3.10+, SQLite y biblioteca estándar; conservar CLI/Tkinter, JSON, matching,
CV/candidaturas y exportaciones. Sin envíos, aprobaciones automáticas, daemon,
despliegue, unidades systemd instaladas, PizzaLab ni Fase 6.

La ejecución autónoma solicitada delega las decisiones rutinarias de diseño.
Se elige orquestación serial reutilizando lectores públicos y matching, persistencia
transaccional por observación y exclusión mutua del sistema operativo. Un servicio
residente o una cola externa añadirían dependencias sin resolver un requisito.
Un lease por PID/TTL permitiría carreras ante pausas/reutilización de PID; se usa
flock/msvcrt, que el kernel libera al terminar el proceso, sin borrar el lockfile.

## Contratos operativos

`jobsearch automation run --config SOURCES_JSON --budget-seconds 120` ejecuta una
vez; fuentes deshabilitadas no generan solicitudes. Default sin config: ninguna.
`--notify` autoriza solo la entrega de avisos mínimos ya configurados. Telegram
requiere además activación y credenciales explícitas por entorno. Nunca CV/contacto,
texto de vacantes, URL/token o datos de perfil en logs/avisos; usar códigos, IDs
internos y contadores. `health`, `runs`, `show` exponen resúmenes redactados.

DRY_RUN=true/AUTO_SUBMIT=false obligatorios. No se crean candidaturas ni se
componen/verifican hechos profesionales automáticamente. Se anuncian borradores
existentes por ID/revisión; el usuario conserva revisión y aprobación exacta.

Bloqueo antes de inicializar/migrar SQLite. Un run interrumpido conserva commits
completos y se marca recuperado por el siguiente dueño del bloqueo. SIGINT/SIGTERM
se convierten en cancelación cooperativa; solicitudes bloqueadas se aíslan en un
subproceso terminable. El presupuesto incluye espera HTTP y procesamiento; limpieza
y commits cortos pueden añadir un margen acotado. SQLite no debe esperar 30 s
silenciosamente fuera del presupuesto: configurar timeout menor y comprobarlo.

Persistir fallos/cooldowns de proveedores entre procesos, incluidos Retry-After e
intervalos mínimos, sin reiniciar pausa al invocar de nuevo. Las cuotas por ejecución
siguen compartidas por proveedor/tableros; sin fuentes nuevas ni scraping. Estado
HTTP se confirma antes/después de cada solicitud y al establecer cooldown.

## Persistencia e idempotencia

Esquema 4 aditivo con backup consistente previo desde 1/2/3. Tablas para runs,
estados HTTP, observaciones/resultados por run y notificaciones. Conservar tablas,
triggers, snapshots y autorizaciones anteriores. Restauración revoca autorizaciones
y pone entregas en curso en estado ambiguo; avisos pendientes no se envían sin
autorización nueva. Rollback mediante backup anterior, nunca downgrade destructivo.

Una observación confirma en una transacción vacante, evaluación y hallazgo. Huella
semántica excluye solo retrieved_at; mismo contenido/perfil/algoritmo reutiliza
evaluación. Cambios conservan snapshots anteriores y revocan aprobaciones conforme
al contrato de Fase 4. No declarar cerrada una vacante porque falte en un resultado
parcial. Los hallazgos son nuevos, cambiados, reevaluados o sin cambio.

## Telegram y Claude

Telegram Bot API sendMessage a host fijo, TLS/proxy normales, sin redirects,
cuerpo/tiempo limitados y transporte simulado en tests. Outbox local con claves
únicas, reintentos finitos ante rechazo inequívoco y cooldown durable. Marcar intento
antes de la red: timeout/crash/respuesta ambigua requieren revisión, no reenvío.
No prometer exactly-once distribuido. Intervalo conservador por chat respeta la
guía oficial; no paid broadcasts ni webhooks/receptor de órdenes.

Claude Code: investigar documentación y acción oficiales. Sin credencial autorizada
no invocar modelos ni simular hallazgos. Preparar workflow manual desactivado,
permisos mínimos, SHA fijo, selección explícita de diff y SHA de PR, revisión humana
para acceso a secretos y ningún checkout/ejecución de código del PR no confiable.
Informe con severidad, evidencia y límites; sin herramientas de escritura/commits.

## Verificación y límites

Tests offline: procesos concurrentes/terminados, recuperación, SQLite histórico,
repetición/cambios/perfil, fuentes parciales, 429/5xx, cuotas/deadline, privacidad,
Telegram opt-in/duplicados/ambigüedad, ausencia de candidaturas/envíos y CLI/GUI.
Suite completa unittest/pytest, pip check/compileall, CI Ubuntu/Windows con
3.10/3.12/3.13. Revisión independiente real de la rama; distinguirla de Claude.
Datos privados sin cifrado: ACL y backups requieren operación humana. No prometer
locks en NFS/FAT ni coordinación de clones o comandos discover independientes.
