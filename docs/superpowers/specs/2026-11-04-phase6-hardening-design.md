# Hardening previo a Fase 6

Misión maestra autorizada: corregir auditoría suministrada, retirar Telegram y
preparar infraestructura/reportes sin despliegue ni modelos externos. Base
`cfa6a4d974ce129a2bc8aeeb4ee4d53b6afc44f7`, PR #10 integrado, CI 74 correcto.
Las pausas de aprobación de diseño se omiten por la instrucción autónoma explícita.

## Entregas

A: rama `codex/phase-6-hardening`, PR a main. M-01/02/03, retirada Telegram/M-04,
L-01/02/03/04 e informativos de recuperación/procesos. B: infraestructura y reportes
en rama posterior apilada, con base/dependencia visible; su preparación está
autorizada sin esperar merge de A. No afirmar integración de ninguno ni tocar
PizzaLab. La orden nueva sustituye restricciones previas contra ramas dependientes.

Python/SQLite/stdlib, formatos y contratos históricos conservados. DRY_RUN=true y
AUTO_SUBMIT=false en todo comando mutante, mantenimiento y unidades futuras.
Ningún sender, bot, webhook, correo, API de modelos o servicio nuevo activado.

## Decisiones de A

1. Reglas conservadoras bilingües por ámbito de puesto. Exclusión confirmada es
ineligible; contradicción es insufficient_information. Menciones incidentales y
negaciones no excluyen. Nueva semántica matching_v3; resultados v2/v1 almacenados
permanecen idénticos y etiquetados. No duplicar el motor histórico completo.
2. Causas locales separadas de proveedor/red/HTTP. Cancelación/deadline detienen
iteración y dejan fuentes posteriores not_attempted. Conservar metadatos recibidos
y Retry-After sin incrementar rachas por respuesta 200 cancelada o terminación.
Reservas previas a red conservan plazo, no inventan fallos del proveedor.
3. Límite compartido de almacenamiento privado: directorios creados/home 0700,
archivos privados 0600 vía descriptor independiente de umask; rechazo de enlaces,
tipos/propietarios no seguros y ancestros reemplazables. No chmod de imports o
padres generales ajenos. Fallback de JSON inválido conserva bytes, pero las
violaciones de almacenamiento escapan al fallback. SQLite principal y sidecars,
backup/restore, documentos y exports pasan por ese límite. Windows exige ACL del
usuario, sin presentar chmod como aislamiento completo.
4. Retirar transporte y configuración Telegram, --notify y productores de eventos.
Conservar tablas/esquema4 como historia; migración5 aditiva con backup y triggers
de solo lectura para tablas retiradas. Copias viejas de código no pueden seguir
llenando esas tablas. No sustituir por mensajería nueva.
5. Retry-After extremo conserva restricción y suspende para revisión manual;
nunca recortar un plazo válido. Estado versionado compatible con versiones previas,
diagnóstico y recuperación auditada que no permiten consultar antes del límite.
Restaurar estados antiguos exige cuarentena/reconciliación de restricciones conocidas.
6. Health usa estado de ejecución más lock OS observado, última ejecución correcta,
frescura y salud de fuentes. Activa legítima no es abandonada; lock ausente con
running sí requiere recuperación. Sin mutación del health.
7. Claude preparado sigue desactivado; revisar debug flags/runner.debug con fuentes
oficiales, minimizar exposición y mantener revisión humana del diff publicable.
CI conserva suites/launchers y crece a 8 jobs, agregando Python3.11 en ambos OS.

## Verificación

Reproducir auditoría antes del cambio; regresiones positivas/adversariales y
compatibilidad, umask000/022, links/owner, WAL/backup/restore, procesos/cancelación,
cinco interrupciones, extremos Retry-After y health activo/abandonado. Revisión
independiente de límite de seguridad y rama, unittest/pytest/pip/compile, CI8/8.
No considerar pruebas sintéticas como conectividad ATS, ejecución Claude o LXC.

## B, después de corregir bloqueos

Preparar instalación fijada por commit, Debian12/Python3.11/venv, usuario y dirs
privados, oneshot+timer horario, backup conjunto/restauración a destino nuevo,
retención solo inventario/dry-run y reporte JSON/Markdown diario 14:00
America/Mexico_City, idempotente/recuperable. Investigar entrega oficial Work;
fallback reporte local privado sin publicar ni enviar. Diseño detallado en su PR.
