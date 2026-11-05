# Preparación de PizzaLab — sin despliegue realizado

Esta entrega B depende del PR #11 (hardening). No está integrada ni instalada en
PizzaLab. No se creó LXC, usuario remoto, timer, puerto, credencial o tarea Work.
El propietario debe revisar e integrar los PRs antes del piloto autorizado.

## Destino y separación

Proxmox VE, **LXC Debian 12 sin privilegios**, Python 3.11, venv, SQLite y systemd
252+. Sin Docker, bases externas, dashboard público, scheduler residente o
actualizador de escritorio. La app corre como `jobsearch-assistant`, sin login,
capacidades o acceso privilegiado al host. No reutilizar un contenedor sin revisar
su propósito y aislamiento.

| Ruta convencional | Uso y permisos |
| --- | --- |
|/opt/jobsearch-assistant/releases/SHA|Código/venv inmutables root-owned, directorios 755 y archivos644/ejecutables755|
|/opt/jobsearch-assistant/current|Enlace administrado a un SHA revisado, no main móvil|
|/etc/jobsearch-assistant|Configuración root:grupo 750; runtime.env 640; sin tokens|
|/var/lib/jobsearch-assistant|Home service-owned 700, perfil/SQLite/resumes/reports 600|
|/var/log/jobsearch-assistant|Archivos privados opcionales; la app emite JSON redactado a journal|
|/var/backups/jobsearch-assistant|Bundles versionados privados 700/600, fuera del checkout|

Layout JSON opcional (`--layout FILE`) ajusta code/state/config/logs/backups/units.
Rutas absolutas ASCII sin espacios/links/ancestros inseguros. No se endurecen
ancestros generales. Si se cambia state fuera de /var/lib, revisar StateDirectory
convencional y drop-in antes de instalar; no asumir adaptación automática de sandbox.

## Release reproducible offline

Autenticar código, manifiesto y toolchain por un canal aprobado. SHA256 detecta
corrupción; no prueba autoría si artefacto y hash vienen del mismo atacante.
El builder exige herramientas ya instaladas con versiones exactas y Git SHA40.
No usa índices, `curl|bash`, build isolation ni main flotante. SOURCE_DATE_EPOCH
proviene del commit; provenance registra archivo Git, herramientas y Python.
No se promete igualdad binaria entre plataformas/toolchains diferentes.

```bash
python scripts/production/build_release.py --repo /checkout/revisado --commit SHA40 \
  --output /artefactos/nuevo --pip-version VERSION_EXACTA \
  --setuptools-version VERSION_EXACTA --wheel-version VERSION_EXACTA
```

En una estación de build confiable preparar previamente pip/setuptools/wheel y
el runtime Debian python3.11/venv/ssl/sqlite3/tzdata. Este proyecto solo necesita
`tzdata` de PyPI en Windows para IANA; Debian utiliza datos del sistema. No se
instalan paquetes del SO desde el script. Revisar la política de suministro y
transferir wheel/manifest/provenance de forma privada.

## Preflight e instalación administrativa futura

Estos comandos son procedimientos para el administrador del LXC; **no se ejecutaron
contra PizzaLab**. El preflight no muta y exige Debian 12, Python 3.11, x86_64/aarch64,
root administrativo, systemd 252/PID1, utilidades, SSL/SQLite/venv e IANA.

```bash
python3.11 scripts/production/manage.py preflight
python3.11 scripts/production/manage.py install --commit SHA40 \
  --manifest /artefactos/manifest.json --wheel /artefactos/archivo.whl --apply
```

Install prepara usuario/grupo dedicados, rutas, config vacía deshabilitada, venv
`--copies`, pip `--no-index --no-deps`, pipcheck, versión de esquema, CLI y smoke
sin fuentes en un HOME temporal. Una reinstalación igual verifica y reutiliza.
No sobrescribe env/unidades distintos ni datos reales: exige revisión manual.
Un fallo conserva una release incompleta no activada para diagnóstico. No crea
perfil real ni certifica hechos profesionales. No activa current, daemon-reload,
timers, fuentes o envíos. No ejecutar el instalador desde la app.

Crear/importar y revisar el perfil JSON real como usuario de servicio en el home
privado antes del primer run operativo. Conservar CV/evidencias fuera de Git.
La configuración de fuentes sigue JSON, explícita y opt-in. Confirmar primero
condiciones actuales, DNS, TLS y conectividad real de Greenhouse/Lever/Ashby.
Sin fuentes, el motor funciona offline y no demuestra acceso a proveedores.

`runtime.env` fija HOME, BACKUPS y LOGS mediante variables
`JOB_SEARCH_ASSISTANT_HOME`, `JOB_SEARCH_ASSISTANT_BACKUPS`,
`JOB_SEARCH_ASSISTANT_LOGS`; DRY_RUN=true/AUTO_SUBMIT=false siempre obligatorios.
No requiere secretos. Si se necesitan credenciales futuras, usar un mecanismo de
systemd apropiado y permisos revisados, no copiar secretos al environment global.

## Activación, actualización y rollback

Detener timers, esperar oneshots, cerrar GUI/manual writers y verificar health.
Crear backup completo reciente y verificarlo como el usuario de servicio. Un
backup de hasta 24 h no prueba ausencia de escrituras posteriores: mantener ventana
de mantenimiento y reconciliar cualquier cambio posterior antes del rollback.

```bash
jobsearch storage backup --output /var/backups/jobsearch-assistant/FECHA-ID \
  --config /etc/jobsearch-assistant/sources.json
jobsearch storage verify-backup /var/backups/jobsearch-assistant/FECHA-ID
# Administrador, después de revisar release y mantenimiento:
python3.11 scripts/production/manage.py activate --commit SHA40 \
  --backup /var/backups/jobsearch-assistant/FECHA-ID --apply
```

Activate/rollback toman el mismo flock y cambian current atómicamente, sin tocar
contenido SQLite. Exigen esquema vivo igual al de la release y backup verificado
reciente; el verificador corre como servicio, no root (evita auxiliares root-owned).
Si todavía no existe DB, el bootstrap no exige backup de una base inexistente.
Si hay una DB importada antes de current, no se omite automáticamente la verificación:
seguir procedimiento manual probado con el administrador.

Cambio de esquema: preservar conjunto previo compatible, restaurar con código
actual a HOME nuevo (revoca permisos/cuarentena), revisar/migrar y cambiar el HOME
solo dentro del mantenimiento aprobado. Rollback a código viejo requiere copia
previa de esquema compatible; nunca bajar el marcador ni abrir esquema nuevo con
código viejo. No se reconstruyen automáticamente datos posteriores a esa copia.
El script rechaza el downgrade incompatible, no simula una restauración segura.

## Unidades y timers

Templates en deploy/systemd y render equivalentes del instalador. `oneshot`,
UMask=0077, StateDirectoryMode=0700, usuario/grupo dedicados, NNP, capacidades vacías,
core 0, TasksMax=16, MemoryMax=512M, CPUQuota=100%, KillMode=control-group, sinRestart.
Búsqueda budget 600 s, **TimeoutStartSec=660** y stop 30 s; RuntimeMaxSec no limita un
oneshot. Reportes TimeoutStartSec=120 y catchup acotado 31 por invocación.
No SuccessExitStatus genérico:0 completo,1 parcial,2 configuración/almacenamiento,
3 concurrencia,4 deadline,130 interrupción conservan significado.

Timer horario con Persistent=true, jitter 120 s, Accuracy 1 s. Reporte a las 14:00 y reintento a las 14:15 en
America/Mexico_City, Persistent sin jitter, con corte fijo a las 14:00. Una recuperación del timer produce
una activación, no una ráfaga por cada hora perdida; report CLI recupera fechas.
After=search ordena si coinciden en una transacción, no garantiza que el informe
incluya la búsqueda de las 14:00. Su ventana y retraso son explícitos.

`namespace-hardening.conf.example` es **opt-in tras validar el LXC**: ProtectSystem,
ProtectHome, PrivateTmp y restricciones de familias/readwrite paths. Namespaces pueden
fallar en LXC no privilegiado. No habilitar nesting, privilegios o capabilities
adicionales para hacerlo pasar. La base no afirma aislamiento namespace; revisar
el drop-in compatible antes del piloto. Sin shell remoto o endpoint público nuevo.
Egress HTTPS allowlist ATS cuando el host lo permita; no evasión proxy/antibot,
Telegram, LinkedIn/Indeed scraping, modelos o sender de candidaturas.

## Evidencia observada y capacidad inicial

Cloud actual: Debian 13/Python 3.12, PID1 distinto de systemd. Preflight rechaza
`debian_12_required`. systemd 257 validó ambos calendarios; verify de las unidades
salió 1: Permission denied creando /run/systemd. No se ejecutaron servicios, aislamiento,
cuentas, timers ni reinicio de LXC. Esto queda pendiente del destino.

Build offline de bee9cce y staging de biblioteca en TEMP: 2.458 s, reinstalación 0.001 s.
Venv limpio ejecutó init/run vacío/reports dos veces/backup/verify/inventory/restore,
todo salida 0. Es validación de desarrollo en Python 3.12, **no** bypass del preflight
ni evidencia Debian 12/Python 3.11. Cambios posteriores se vuelven a verificar en el PR.

Medición sintética con worker spawn, 250 ofertas y dos runs: 7.521 s,250 nuevas y luego
250 sin cambios; parent peak RSS 24540 KiB, worker 23516 KiB, almacenamiento 7708762 bytes.
Sin red; dos procesos simultáneos esperados (padre+worker). No es carga de proveedor
real ni garantía de memoria máxima. SQLite/evaluaciones/snapshots crecen con volumen.
Propuesta inicial ajustable: 1 vCPU, 512 MiB RAM y disco privado ≥4 GiB; MemoryMax=512M debe
probarse con datos y snapshots representativos, no deriva de una medición de LXC.

## Checklist piloto pendiente

- [ ] Revisión e integración de PRs; main protegido/revisión requerida por propietario.
- [ ] Acceso administrativo autorizado al LXC nuevo, Debian 12/Python 3.11/systemd 252.
- [ ] Usuario, ACL/permisos, rutas, zona, DNS/TLS y egress ATS reales comprobados.
- [ ] Perfil/hechos/evidencias revisados; fuentes inicialmente deshabilitadas.
- [ ] Preflight, release autenticada, install/reinstall/activate y esquema compatible.
- [ ] Run sin fuentes y después consultas ATS autorizadas de términos vigentes.
- [ ] SIGTERM, SIGKILL/reinicio, health, concurrencia y pausas/reintentos reales.
- [ ] Backup conjunto/restore hacia nuevo HOME, CV íntegro, capacidades revocadas,
      fuentes en cuarentena y rollback sin pérdida silenciosa.
- [ ] systemd-analyze verify/calendar, usuario/permisos/aislamiento/LXC y exit codes.
- [ ] Recurso/disco lleno controlado, retención simulada, journal y alertas privadas.
- [ ] Reporte14:00, fecha/zona/catchup/idempotencia; ninguna simulación como envío.
- [ ] Activar timers únicamente tras piloto autorizado; guardar evidencia privada.

Codex Cloud no es alojamiento permanente. Sin validación del host y conectividad
real no declarar preparado/desplegado en producción.

Referencias oficiales revisadas: [systemd.service Debian 12](https://manpages.debian.org/bookworm/systemd/systemd.service.5.en.html),
[systemd.timer](https://manpages.debian.org/bookworm/systemd/systemd.timer.5.en.html),
[systemd.time](https://manpages.debian.org/bookworm/systemd/systemd.time.7.en.html),
[systemd.exec](https://manpages.debian.org/bookworm/systemd/systemd.exec.5.en.html),
[Debian 12/venv](https://www.debian.org/releases/bookworm/amd64/release-notes/ch-information.en.html)
y [pip instalaciones repetibles](https://pip.pypa.io/en/stable/topics/repeatable-installs/).


## Integración de las ramas apiladas (sin ejecutarla en esta entrega)

#12 incorpora 875585782d9672ae0879e2c415b3ca7467b9db37 de #11 mediante merge local,
conservando como ancestro 50a2b157748276a555a3a28a06580b3979a816b5 y sus siete commits
propios. No se hizo rebase o force-push. El diff contra #11 conserva solo preparación
operativa y N-02; no vuelve a presentar el motor de elegibilidad como cambio propio.

Cuando el propietario autorice integración, preferir merge de #11 preservando su
ascendencia. Después retargetear #12 a main y verificar merge-base/diff y CI antes de
integrarlo. Si #11 se integra por squash/rebase remoto, no asumir la ascendencia:
preparar una rama nueva desde main actualizado y trasladar solo los siete commits
propios originales de #12 más el commit N-02, excluyendo el merge de hardening.
Comparar árboles/diff y repetir CI. Conservar la rama original; no reescribirla ni
forzar un push para ocultar duplicados. Ninguna de estas integraciones se realizó.
