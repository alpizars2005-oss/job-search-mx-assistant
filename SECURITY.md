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
vigencia independiente ni elegibilidad desde México. Las pausas y cuotas son en
memoria, no coordinan procesos diferentes. El timeout es por operación de socket,
no un límite total contra respuestas lentas. No agregar un scheduler que omita
esas limitaciones. Detalles en [JOB_SOURCES](docs/JOB_SOURCES.md).

## SQLite y elegibilidad — Fase 3

La migración valida la versión antes de cambiar el esquema y crea un backup
consistente con la API SQLite; no copiar solo el archivo principal si hay WAL.
Un fallo revierte la transacción; la recuperación manual restaura hacia un archivo
nuevo y conserva el original. Las identidades y snapshots se escriben con
restricciones únicas y transacciones. La API local no representa autorización de
envío. Los snapshots y backups contienen perfiles privados completos: mantenerlos
fuera del repositorio y aplicar permisos/ACL del sistema; no son cifrados.

`matching_v2` procesa texto como datos y utiliza reglas deterministas acotadas.
Ningún campo ATS ni puntaje confirma elegibilidad legal por sí solo; las afirmaciones
del empleador son evidencia observada, no verificación jurídica independiente.
La falta de información esencial conserva `insufficient_information`. La versión
histórica `legacy_v1` se mantiene para lectura/reproducción, no para filtrar ofertas
nuevas. Límites, operación y rollback en [SQLITE_MATCHING](docs/SQLITE_MATCHING.md).
