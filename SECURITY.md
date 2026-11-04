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
