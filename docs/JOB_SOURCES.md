# Descubrimiento de vacantes públicas — Fase 2

La Fase 2 agrega lectores GET de Greenhouse, Lever y Ashby, normalización,
procedencia y deduplicación en memoria. No utiliza perfiles, puntuaciones,
SQLite, navegador, credenciales o mecanismos de envío. La GUI, tracker y
exportaciones anteriores conservan sus contratos.

## Uso y activación explícita

```bash
jobsearch discover
jobsearch discover --config examples/sources.example.json
```

Ambos comandos son seguros por defecto: el primero no configura fuentes y el
segundo devuelve tres reportes `disabled`, sin conexiones. También pueden
invocarse con `python -m jobsearch_assistant` en el entorno instalado.

Copiar el ejemplo a una ubicación propia fuera del repositorio y cambiar
`enabled` a `true` solo en los tableros que se desee consultar, después de
revisar sus condiciones y acceso de red. No activar todo el catálogo por
consecuencia de importarlo. Ejemplo mínimo de configuración explícita:

```json
{
  "schema_version": 1,
  "sources": [
    {"provider": "greenhouse", "board": "gitlab", "company": "GitLab", "enabled": true}
  ]
}
```

```bash
jobsearch discover --config /ruta/externa/sources.json --language es
```

`--language en` ofrece errores de configuración en inglés. Los datos y códigos
JSON usan identificadores estables en inglés. La salida es JSON en stdout;
no se guarda automáticamente. Códigos de salida: **0** consulta completa o
fuentes deshabilitadas, **1** error/pausa/resultados parciales, **2** configuración
inválida. Un resultado parcial puede contener vacantes útiles, pero no acredita
que se revisó el tablero completo.

La configuración JSON de fuentes es independiente de `profile.json` y de los
ajustes personales. Tiene máximo 64 KiB y 100 tableros; rechaza claves
repetidas/desconocidas, tipos incorrectos, proveedores no soportados y tableros
duplicados. No admite URLs base configurables. `sources/companies.yaml` sigue
siendo referencia documental; no requiere PyYAML ni cambia la importación de
perfiles JSON. Ninguna opción de descubrimiento implica autorización de envío.

## Fuentes implementadas y documentación consultada

Consulta oficial: 2026-11-04. Las condiciones generales de servicios contratados
no equivalen a una licencia universal de redistribución de todo contenido.
Usar únicamente publicaciones públicas y revisar las condiciones de cada empresa;
un endpoint documentado no garantiza su disponibilidad, gratuidad permanente o
permiso de contratación desde México.

| Fuente | Lectura implementada | Contrato y condiciones |
| --- | --- | --- |
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true` | [Job Board API](https://docs.greenhouse.io/job-board.html) documenta GET sin autenticación y separa POST. Una respuesta completa, sin inventar paginación de Harvest. [MSA, API Usage](https://www.greenhouse.com/master-subscription-agreement) exige uso no abusivo y permite límites por contrato; no se trasladan cuotas de otros productos |
| Lever | `GET https://api.lever.co/v0/postings/{board}?mode=json&skip=N&limit=M` | [Postings API](https://github.com/lever/postings-api) documenta publicaciones públicas, campos y skip/limit; su límite de 2 POST/s corresponde a candidaturas y no se presenta como cuota GET. [Términos](https://www.lever.co/legal/terms-of-service) condicionan uso del servicio; no se accede a datos privados. Esta versión soporta la instancia global, no la EU |
| Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{board}` | [Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api) describe el listado por tablero y campos que pueden faltar. No usa los endpoints autenticados `jobPosting.list`. [Condiciones](https://www.ashbyhq.com/resources/terms) prohíben eludir controles o sobrecargar el servicio |

Los tres adaptadores están implementados y probados con respuestas sintéticas.
Las cuotas siguientes son límites conservadores del cliente, no límites oficiales
prometidos por los proveedores. No se identificó en las referencias consultadas
una cuota numérica GET aplicable a los tres endpoints públicos que obligara a
sustituir los valores iniciales del plan.

## Seguridad y límites configurables

Todos los campos de `limits` son opcionales; el ejemplo enumera sus defaults:

| Opción | Default | Alcance |
| --- | --- | --- |
| `timeout` | 15 s | Timeout de operaciones de socket de urllib, no deadline total de toda la ejecución |
| `max_requests` | 20 | Por proveedor y ejecución, sumando todos sus tableros, páginas y reintentos |
| `max_retries` | 3 | Reintentos adicionales por solicitud; también consumen la cuota anterior |
| `backoff_base` / `max_backoff` | 1 / 30 s | Exponencial con jitter entre 50 % y 100 % del escalón, hasta el máximo |
| `max_wait` | 30 s | Espera acumulada por proveedor/ejecución, incluyendo intervalo, backoff y Retry-After |
| `min_interval` | 1 s | Intervalo mínimo entre inicios de solicitudes al mismo proveedor |
| `error_threshold` / `pause_seconds` | 5 / 300 s | Errores consecutivos antes de pausar; una página válida reinicia el contador |
| `max_response_bytes` | 5 MiB | Lee como máximo el límite más un byte para detectar exceso |
| `max_pages` / `page_size` | 10 / 100 | Solo Lever; una página llena al alcanzar el máximo marca `page_limit` |

Los límites se validan como números finitos: no se aceptan booleanos como
enteros. Hay topes adicionales de configuración (1000 solicitudes, 10 reintentos,
20 MiB por respuesta, 100 páginas y 1000 registros por página solicitada).

- Hosts y rutas API exactos construidos localmente, solo HTTPS, sin userinfo,
  puertos explícitos, fragmentos, controles, backslashes o parámetros arbitrarios.
  No se consume una URL `next`, `applyUrl`, enlace HTML o recurso de la respuesta.
- Todas las redirecciones se rechazan, incluso entre hosts conocidos. Un cambio
  legítimo de endpoint requiere revisar/adaptar el contrato, no ampliar la red.
- Las URLs de ofertas se validan contra hosts de páginas del ATS, tablero e ID;
  se preserva mayúsculas/minúsculas. URLs externas/custom domain o ambiguas se
  rechazan con `unsafe_job_url`. Nunca se descargan para completar información.
- TLS, CA y proxy del entorno se conservan; no hay cookies, login, POST o bypass.
- Reintentos solo ante fallo de red, 429 y 5xx. Otros 4xx, redirects, JSON inválido,
  HTML o formatos inesperados terminan ese intento de tablero. No se registran
  cuerpos, URLs rechazadas ni excepciones con información privada.
- `Retry-After` acepta segundos enteros o fecha HTTP con zona. Nunca se reduce
  al máximo de backoff; si no cabe en la espera restante, se pospone la fuente.
  Un encabezado inválido provoca pausa conservadora. Su cooldown se respeta
  incluso si se agotaron los reintentos y se consulta otro tablero del proveedor.
- JSON estrictamente UTF-8, sin claves duplicadas o NaN/Infinity; tipo de contenido
  JSON obligatorio y respuestas comprimidas rechazadas. Una página completamente
  inválida cuenta como fallo del proveedor; páginas mixtas conservan registros
  válidos, contabilizan rechazos y se reportan como parciales.

El estado de cuota/pausa existe **en memoria**. Se comparte entre tableros y las
pausas se conservan entre `run()` del mismo cliente. Un proceso CLI nuevo no
hereda cooldowns: no ejecutar en bucle para eludirlos. Persistencia y coordinación
entre procesos corresponden a las fases posteriores. El timeout de socket no
impide por sí mismo una respuesta que avance lentamente; no se promete un
presupuesto global de tiempo real para toda la ejecución.

## Formato normalizado y procedencia

Cada elemento de `jobs` contiene:

- `source`, `source_board`, `source_job_id`: proveedor, tablero e identidad estable.
  Greenhouse usa `id`, Lever usa `id`, Ashby extrae la identidad del path de
  `jobUrl` validado, porque el listado documentado no garantiza un campo `id`.
  No se construyen IDs a partir del título, índice o fecha de descarga.
- `company`: nombre configurado explícitamente; su procedencia es configuración,
  no una verificación independiente del empleador.
- `title`, `locations`, `work_mode`, `url`, `description`, `published_at`,
  `retrieved_at`, `verification_status`, `eligibility_evidence` y `provenance`.

Campos ausentes permanecen `null`, `[]` o `unknown`; no se inventan títulos,
ubicaciones o fechas. HTML se convierte a texto con HTMLParser sin resolver
recursos; scripts/estilos se omiten. Lever combina descripción, listas y cierre.
Las fechas presentes válidas se normalizan a UTC; `updated_at` de Greenhouse
no se hace pasar por fecha de publicación. Lever no promete publicación en el
contrato consultado, por lo que `published_at` queda `null`.

`work_mode` solo interpreta campos explícitos del ATS, no palabras de ubicación
o descripción. Según el [contrato de Ashby](https://developers.ashbyhq.com/docs/public-job-posting-api),
`isRemote=true` incluye tanto `Remote` como `Hybrid`; `workplaceType` conserva
la distinción `remote`/`hybrid`. `OnSite + false` produce `onsite`. Las
combinaciones contradictorias (`Remote/Hybrid + false`, `OnSite + true`) y una
modalidad desconocida quedan `unknown`: el booleano por sí solo no identifica
trabajo totalmente remoto. Una modalidad explícita válida puede conservarse
si falta el booleano. `Remote`, `Global`,
`Americas`, `AMER` e incluso una ubicación México no prueban autorización
contractual: `eligibility_evidence.status` permanece **unknown** para México,
con observaciones y origen para una evaluación posterior.

`listed` indica observación de una publicación suficientemente completa en el
endpoint de listado en `retrieved_at`; no verifica independientemente vigencia
legal, respuesta del empleador o elegibilidad. `incomplete` indica ausencia de
título, descripción, ubicación o URL. Ashby `isListed=false` se omite. Un registro
sin identidad estable o con tipos/URL inválidos se rechaza. `provenance` asocia
campos a URL de consulta + ruta JSON, configuración o regla de transformación;
marca las rutas ausentes como `missing:campo`, distinguiéndolas de campos
presentes con valor `null`. No atribuye datos ausentes a rutas observadas.

La identidad de deduplicación es `(source, source_board, source_job_id)`.
La primera aparición válida gana, manteniendo orden de configuración/paginación.
No se colapsan empresas/tableros ni proveedores diferentes por compartir título
o número. Los offsets Lever avanzan por registros recibidos, incluyendo rechazos,
para evitar volver a consultar páginas por efecto del filtrado.

## Fuentes evaluadas y diferidas

No se integraron las cuatro fuentes adicionales automáticamente:

| Fuente | Evidencia oficial | Decisión de esta entrega |
| --- | --- | --- |
| Remotive | [API y condiciones](https://remotive.com/remote-jobs/api), [documentación oficial](https://github.com/remotive-com/remote-jobs-api): atribución/enlace obligatorio, retraso de 24 horas, restricciones de redistribución; aconseja máximo 4 consultas diarias y bloquea exceso de 2/minuto | Diferir hasta diseñar atribución y presupuesto diario que no se reinicie con cada CLI; la cuota por ejecución de ATS no cubre ese contrato |
| Remote OK | [FAQ oficial](https://remoteok.com/faq) confirma JSON/RSS públicos sin autenticación y exige atribución/enlace al compartir; [condiciones](https://remoteok.com/legal) consultadas | Diferir: falta validar esquema operativo, cuotas y comportamiento real bajo los límites de red de Cloud; no se presume inestabilidad ni prohibición |
| Get on Board | [Manual oficial](https://www.getonbrd.com/user-manual/get-on-board-s-api) distingue API pública y privada; [referencia técnica](https://api-doc.getonbrd.com/?version=latest), [condiciones](https://getonbrd.com/about/tos) | Diferir: revalidar contrato técnico, cuotas y condiciones por endpoint; no usar la API privada ni contratar un plan |
| Working Nomads | [Condiciones oficiales](https://www.workingnomads.com/terms-and-conditions) describen listados públicos y suscripciones | No integrar: no se verificó documentación oficial de una API/feed estable y permiso específico de automatización. Un endpoint citado por terceros no basta |

LinkedIn e Indeed continúan excluidos de conectores; no se implementa scraping ni evasión
antibot. Los enlaces manuales existentes no se transformaron en recolectores.

## Pruebas y comprobación real en Cloud

La suite utiliza cuerpos/transportes/relojes sintéticos sin servicios externos.
La revisión final agregó regresiones para respuestas chunked truncadas/errores
de protocolo, límites numéricos excesivos y procedencia de campos ausentes:

```bash
python -m unittest discover -s tests -v
python -m pytest -q
python -m pip check
python -m compileall -q src scripts tests run_cli.py run_gui.py
python -m jobsearch_assistant discover
python -m jobsearch_assistant discover --config examples/sources.example.json
```

En este Cloud con Python 3.12.14, tras corregir la modalidad Ashby: **73 pruebas unittest**
y **73 pruebas pytest + 205 subtests**, aprobadas. CSV se convirtió a TestCase,
por lo que las dos pruebas previas ya se ejecutan en la matriz CI existente,
sin añadir pytest como requisito de CI o una dependencia nueva de runtime.
Los casos cubren todos los escenarios obligatorios: válido/incompleto/vacío,
JSON/HTML, timeout, 429/5xx, ambas formas Retry-After, paginación, URLs/redirects,
deduplicación, normalización, información regional desconocida, cuotas y reintentos.

Consulta real autorizada intentada el 2026-11-04 con configuración temporal de
GitLab/Greenhouse, dLocal/Lever y Supabase/Ashby: `max_requests=1`,
`max_retries=0`, `timeout=3`, `max_wait=0`, `min_interval=0`. El comando devolvió
**1**, cero vacantes y un reporte `network_error` con una solicitud por proveedor.
Una comprobación diagnóstica adicional a Greenhouse identificó `URLError` con
`OSError` debido a rechazo **403 del túnel proxy**. La política de red restringida
no incluye estos hosts. No se obtuvieron respuestas de los ATS ni se infiere su
estado a partir del fallo. No se modificaron rutas, proxy, CA o permisos de red.
Los tableros del catálogo conservan su evidencia documental anterior.

## Límites y continuación

Veredicto de esta fase: lectores y controles verificables de forma offline;
validación real contra proveedores pendiente de acceso de red autorizado.
No se agregaron nuevas tablas, migraciones, matching, candidaturas, Telegram,
scheduler, Claude o cambios en PizzaLab. La Fase 3 requiere integrar el PR de
esta fase y autorizar el siguiente alcance; deberá añadir unicidad transaccional,
migraciones y elegibilidad sin reinterpretar silenciosamente los datos históricos.
