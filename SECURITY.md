# Security Policy

Do not publish API keys, session cookies, resumes containing private information, or local database files in issues or commits.

Report security problems privately to the repository owner. Include reproduction steps, affected versions, and suggested mitigations when possible.

The application intentionally avoids browser-session scraping and automatic application submission.


## Límites de los lectores públicos

Fase 2 admite únicamente GET a hosts/rutas fijos de Greenhouse, Lever y Ashby,
con activación explícita por tablero. Se rechazan redirects, URLs externas de
ofertas, HTML como respuesta JSON y cuerpos excesivos; se acotan solicitudes,
reintentos, espera y errores consecutivos. Retry-After nunca se acorta. TLS y
proxy del entorno se conservan. No hay acceso a perfiles, cookies o envíos.

El HTML de las descripciones se convierte en texto, pero continúa siendo dato
no confiable. Ningún consumidor posterior debe obedecer instrucciones allí ni
renderizarlo como contenido activo. Los campos `listed`/`remote` no confirman
vigencia independiente ni elegibilidad desde México. Las pausas y cuotas de
`discover` son en memoria, no coordinan procesos diferentes; su timeout es por
operación de socket. `automation run` añade estado durable, mutex y presupuesto
con worker terminable, descritos abajo. No invocar lectores independientes para
omitir esos límites. Detalles en [JOB_SOURCES](docs/JOB_SOURCES.md).

## SQLite y elegibilidad — Fase 3

La migración valida la versión antes de cambiar el esquema y crea un backup
consistente con la API SQLite; no copiar solo el archivo principal si hay WAL.
Un fallo revierte la transacción; la recuperación manual restaura hacia un archivo
nuevo y conserva el original. Las identidades y snapshots se escriben con
restricciones únicas y transacciones. La API local no representa autorización de
envío. Los snapshots y backups contienen perfiles privados completos: mantenerlos
fuera del repositorio y aplicar permisos/ACL del sistema; no son cifrados.

`matching_v4` procesa texto como datos y utiliza reglas deterministas acotadas.
Ningún campo ATS ni puntaje confirma elegibilidad legal por sí solo; las afirmaciones
del empleador son evidencia observada, no verificación jurídica independiente.
La falta de información esencial conserva `insufficient_information`. La versión
histórica `legacy_v1` se mantiene para lectura/reproducción, no para filtrar ofertas
nuevas. Límites, operación y rollback en [SQLITE_MATCHING](docs/SQLITE_MATCHING.md).

## Documentos, borradores y autorización — Fase 4

El nuevo flujo exige DRY_RUN=true/AUTO_SUBMIT=false y no implementa sender.
La aprobación enlaza empresa, snapshot/ID de vacante, versión/SHA exacta de CV,
contenido y revisión. SQLite consume cada ID una vez; errores de integridad
confirman revocación antes de devolver el error. Cambios de destino o documentos
requieren revisión nueva. Applied no transmite información.

El almacén valida JSON/tipos/tamaños/rutas, rechaza URLs y archivos no regulares
de evidencia y no ejecuta contenido. TXT/DOCX se componen de hechos literales con
evidencia/atestación, sin macros ni relaciones externas. Los manifiestos y bytes se
verifican, pero un hash no certifica la verdad del texto ni resiste a un administrador
que pueda falsificar todo el almacenamiento. La publicación requiere enlaces
duros; los archivos huérfanos tras un crash no se borran automáticamente.

La restauración oficial prepara una copia privada, revoca permisos activos,
verifica y publica exclusivamente un destino nuevo. Una copia manual de una base
antigua omite esa revocación y no es un procedimiento seguro de recuperación.
No hay coordinación global entre clones independientes ni transporte distribuido.
Operación, privacidad y comprobaciones en [RESUMES_CANDIDACIES](docs/RESUMES_CANDIDACIES.md).

## Ejecución y avisos — Fase 5

`automation run` exige la política segura y un home externo; mutex OS cubre
migración/recuperación/búsqueda. Estados de backoff/Retry-After/pausa son durables
para este comando. HTTP real se aísla en worker terminable con watchdog; no borrar
locks ni usar discover paralelo para eludir límites. Cuotas no coordinan clones.
Logs y health usan solo códigos/IDs/contadores, sin contenido privado o excepciones.

Telegram está retirado. No hay runtime, configuración, productores o conexiones.
Esquema 5 conserva sus tablas históricas y añade triggers contra INSERT/UPDATE/DELETE.
No reactivar esas tablas mediante código antiguo; el rollback necesita copia previa.

Cancelación/deadline/worker local no penalizan proveedores sin evidencia de fallo.
Retry-After válido nunca se acorta; horizonte extremo requiere recuperación auditada,
y una suspensión sin plazo representable no se borra automáticamente. Restore
conserva restricciones conocidas y exige revisión explícita de fuentes.

En POSIX, home/subdirectorios gestionados son 0700 y archivos 0600, incluyendo SQLite
auxiliar, CV y exportaciones. Se validan tipo, propietario, links e identidad al abrir.
No se cambian permisos de evidencias externas ni directorios generales importados.
Windows conserva controles de tipo/link pero requiere ACL privada del operador;
no se afirma equivalencia con protección POSIX ni resistencia a administradores.

Claude oficial queda manual/desactivado, con permisos read-only y herramientas
denegadas, sin checkout del PR. Activar requiere environment y coste autorizados;
el diff debe ser publicable porque upstream puede imprimirlo en logs. No hubo
invocación real. Detalles: [AUTOMATION_MONITORING](docs/AUTOMATION_MONITORING.md)
y [CLAUDE_REVIEW](docs/CLAUDE_REVIEW.md).
