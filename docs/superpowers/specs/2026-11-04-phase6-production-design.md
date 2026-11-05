# Diseño B — preparación operativa y reportes (propuesto)

Dependencia explícita: rama A codex/phase-6-hardening. B tendrá PR apilado dirigido
a A, manteniendo su dependencia visible y sin afirmar integración/despliegue.
Ningún cambio real en PizzaLab, timer, cuenta Work, Claude o mensajería.

1. Reportes: artefactos fechados inmutables bajo reports/YYYY-MM-DD, JSON/Markdown
   más manifiesto SHA256. Archivos como registro de idempotencia sin schema6.
   Ventana anterior14→actual14 America/Mexico_City, catchup acotado y explícito,
   metadatos de candidaturas/CV actuales etiquetados al generar (no inventar pasado).
   Exportación agregada separada; URLs solo validadas, vigencia independiente desconocida.
   Applied manual / aprobación / simulación / receipt real distintos; real confirmado0.
2. Bundle privado: RunLock automation.lock; SQLite backupAPI y copias verificadas de
   configuración/CV/evidencias/reportes. Captura de archivos con huellas antes/después,
   rechazar cambios/link/objeto extraño. Mutaciones del CLI comparten el mismo lock
   para evitar snapshots incompatibles; APIs embebidas requieren coordinación del caller.
   Publicación atómica de directorio exclusivo, fsync, manifiesto exacto de archivos.
   Restore verifica hashes/integridad, nuevo destino, revoca aprobaciones/quarantena
   fuentes con restore_backup; no copiar capacidades sin esa guardia.
3. Retención solo inventario/simulación: edades/tamaños/candidatos configurables,
   conserva referencias/últimos respaldos, nunca elimina. Un enlace inseguro falla.
4. Infra offline fijada por SHA+wheels/hash revisados: preflight Debian12/Python3.11,
   usuario dedicado, releases rootowned/data privados, sinautoupdater, activar aparte.
   Rollback solo mismo esquema o copia previa compatible con revisión de fuentes.
5. systemd252: oneshot, UMask0077, datos0700, NNP, caps vacías, budget600s,
   TimeoutStartSec>budget, controlgroupkill, hourly Persistent+jitter; daily14local.
   Restricciones namespace son dropinoptin tras comprobar LXC, nunca nesting adicional.
6. Work: no endpoint de entrega verificado al chat ni acceso privado LXC. Reportes
   locales completos; generated/stored true, delivered/read false/unknown. No tarea,
   Drive/email o sustituto activados. Documentación oficial y bloqueos explícitos.

Pruebas: TDD sintético por módulo; concurrencia/subprocesscancel/restart/atomicpublish,
checks hash/migración/restore/CV/policy, backup falla disco/no sobrescritura, retención
sin borrado, instalación offline en sandbox, sintaxis/calendar reales si disponibles.
Full unittest/pytest/pipcheck/compile +8CI jobs en SHA final de B. Medir recursos
sintéticos, separar inferencias del LXC real no disponible. Checklist piloto obligatorio.
