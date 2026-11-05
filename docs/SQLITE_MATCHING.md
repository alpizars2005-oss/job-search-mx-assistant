# SQLite y matching explicable — Fase 3

**Continuidad en Fase 5:** esquema actual 4 con historial operativo y notificaciones;
matching y snapshots anteriores se conservan. Ver [migración/rollback](AUTOMATION_MONITORING.md).

Este documento conserva el contrato de entrega de Fase 3, integrada en PR #8.
Fase 4 amplía SQLite a esquema 3 y agrega documentos/candidaturas; consultar
[backup conjunto, rollback y autorizaciones](RESUMES_CANDIDACIES.md). El matching
`matching_v2` y los datos históricos descritos aquí se conservan.

Base: PR #7 integrado en `main`, commit `5932de7baa9df938d52fcdd6888ed927625bc49a`.
Se extiende el núcleo existente, sin dependencias de runtime nuevas, servicios,
envíos ni despliegues. Las reglas son una ayuda de revisión, no una certificación
jurídica ni una probabilidad de contratación.

## Operación y compatibilidad

```bash
jobsearch discover
jobsearch discover --config /ruta/externa/sources.json --save
jobsearch vacancies list
jobsearch vacancies evaluate 1 --json
jobsearch vacancies evaluate 1 --language es
jobsearch analyze examples/job-posting.txt --language en --json
```

`discover` conserva JSON y no accede al perfil/base sin `--save`. Los lectores
siguen deshabilitados por defecto y sujetos a [los límites de Fase 2](JOB_SOURCES.md).
`--save` conserva cada `NormalizedJob`, procedencia, campos desconocidos y la
evaluación con el perfil actual. No crea una candidatura en el tracker. La salida
añade `saved` con `vacancy_id`, `evaluation_id` y `evaluation`; los reportes parciales
siguen dando código 1. Errores de configuración/persistencia dan código 2.

`vacancies list` devuelve las observaciones guardadas; `vacancies evaluate` no
consulta la red y evalúa explícitamente el snapshot local actual. Cada resultado
incluye algoritmo, evidencia, requisitos, restricciones, desconocidos y sugerencias.
Los comandos `analyze`, `applications`, `profile`, `export`, la GUI y los launchers
conservan sus entradas anteriores. Las exportaciones del tracker siguen separadas
del catálogo de vacantes; no exportan perfiles completos de snapshots por accidente.

La GUI muestra la misma explicación bilingüe que la CLI. Su formulario conserva
los hechos opcionales al editar los campos anteriores. Esos hechos se configuran
en JSON; no se añade un formulario que sugiera datos profesionales no verificados.

## Perfil JSON y datos desconocidos

Los perfiles anteriores siguen cargando. Los campos nuevos son opcionales y no
se infieren de habilidades, titular, proyectos o ubicación:

| Campo | Tipo y significado |
| --- | --- |
| `residence_country` | Código de dos letras, p. ej. `MX`, o `null` |
| `work_authorized_countries` | Lista de códigos o `null`; declaración del candidato, no permiso del empleador |
| `experience_years` | Número finito entre 0 y 100 o `null`; solo experiencia documentada |
| `degree_completed` | Booleano o `null`; estudiante no implica título concluido |
| `language_levels` | Objeto idioma→nivel declarado: A1–C2, native/basic/intermediate/advanced/fluent |
| `conditions` | Objeto de condiciones→`true`/`false`/`null` |

`null` significa desconocido; `false` no equivale a ausencia. No completar estos
datos por conveniencia para mejorar un score. La importación valida tipos sin
repetir datos privados en errores. La recuperación histórica ante un JSON inválido
permanece: usa un perfil predeterminado en memoria sin reescribir el archivo;
verificarlo antes de guardar o evaluar una candidatura importante.

Las condiciones reconocidas usan claves estables, entre ellas `security_clearance`,
`weekend_work`, `travel`, `driver_license`, `degree_in_progress` y
`equivalent_experience`. Una matrícula obligatoria desconocida no se confunde
con la ausencia de un título terminado obligatorio. Las
certificaciones específicas requieren su clave específica, no una afirmación
genérica de que se posee alguna certificación. No declarar una condición como
verdadera sin respaldo; las condiciones obligatorias no reconocidas requieren
revisión y permanecen desconocidas.

## Elegibilidad antes del puntaje

El motor nuevo es `matching_v2`. Primero identifica requisitos con estados
`met`, `unmet`, `unknown`, `contradictory` o `not_required`, motivos y evidencia.
Después calcula compatibilidad solo con señales observadas.

- Una exclusión confirmada produce `ineligible`, independientemente del score.
- Falta de información esencial o contradicciones sin resolver produce
  `insufficient_information`. Un puntaje alto en habilidades no supera ese estado.
- Con información esencial suficiente: `high_priority` 80–100,
  `medium_priority` 65–79, `manual_review` 50–64 y `rejected` 0–49.
  Una ambigüedad no esencial también puede requerir revisión manual.

Se consideran contratación desde México, modalidad, restricciones geográficas,
experiencia obligatoria, título terminado, seniority, idiomas y condiciones
adicionales reconocidas. Una afirmación explícita del empleador sobre contratar
residentes de México se conserva como evidencia textual; no se verifica de forma
independiente ni se transforma en autorización legal universal.

`Remote`, `Global`, `Americas`, `LATAM`, ubicación México y autorización personal
para trabajar no bastan para probar ese permiso. Hybrid sigue siendo híbrido y
no satisface `remote_only=true`. Negaciones como `not remote`, `US residents only`,
`no degree required` y requisitos deseables se distinguen de afirmaciones
obligatorias en los patrones cubiertos. La ausencia de salario no excluye ni
aporta puntos; no se inventan sueldo, moneda o conversiones.

Los años totales del perfil no demuestran años en una tecnología o puesto
específico. Ese requisito permanece pendiente cuando no existe evidencia de su
alcance. Los permisos personales para trabajar se evalúan por país reconocido;
un país o combinación de países no resuelta conserva un requisito desconocido.
“We may hire” o una intención de contratar no confirman un permiso actual.

El desglose de compatibilidad suma hasta 100 sin base de puntos automática:
habilidades declaradas coincidentes hasta 35, rol objetivo 20, nivel junior 10,
remoto confirmado 10, ubicación preferida observada 5, idioma requerido declarado
7, experiencia obligatoria confirmada 5 y permiso explícito del empleador México
8. Cada aporte incluye evidencia de los campos utilizados. Una coincidencia de
ubicación aporta compatibilidad, pero no satisface el requisito de permiso legal.

Las reglas de texto son acotadas, bilingües y deterministas. No son comprensión
general de lenguaje: una condición jurídica no reconocida, redacción ambigua,
excepciones o contradicciones requieren leer la publicación y consultar al
empleador. El motor no ejecuta instrucciones incluidas en descripciones.

## Esquema 2, identidades e históricos

La inicialización valida `meta.schema_version` antes de modificar el esquema.
Una base vacía se crea en versión 2; la versión 1 recibe backup previo y migración
en una transacción explícita. Versiones futuras/no soportadas se rechazan en lugar
de sobrescribir el marcador. No se usa `executescript` con commits intermedios.

La tabla `applications` conserva todas sus filas, IDs, fechas, notas, estados y
`evaluation_json`, incluidos duplicados históricos. Las evaluaciones antiguas
sin versión se leen como `legacy_v1`, manteniendo score y etiquetas anteriores.
`evaluate_job_legacy` reproduce el algoritmo anterior; no se ejecuta una
reevaluación masiva ni se reemplazan `strong_fit`/`review_risk` históricos.

Las nuevas tablas separan identidades manuales, vacantes normalizadas y
evaluaciones. La identidad de fuente es `(source, source_board, source_job_id)`;
no se colapsan proveedores/tableros por título. Para el tracker manual se usa URL
sin convertir su ruta a minúsculas, o una heurística de empresa/título cuando
falta URL. Esa heurística no detecta republicaciones o variantes entre proveedores.
Los duplicados históricos siguen visibles; el registro de identidad elige uno
para impedir nuevas inserciones repetidas sin borrar datos.

Las evaluaciones guardan snapshots del perfil y de la vacante realmente evaluada,
JSON canónico, huellas y versión. Iguales entradas/versión son idempotentes;
entradas nuevas permiten otra evaluación sin cambiar las anteriores. El snapshot
incluye la observación completa, por lo que otra fecha de recuperación puede
representar otra entrada. Los hashes aportan trazabilidad, no anonimización.
Las transacciones y restricciones únicas coordinan escritores SQLite locales;
no se promete coordinación de cuotas HTTP entre procesos ni soporte de un sistema
de archivos de red con bloqueos incompatibles con SQLite.
Se conserva el modo de journal existente; una base nueva usa el predeterminado
de SQLite. La inicialización no fuerza un cambio de journal en una base anterior.

## Backup, recuperación y rollback

Antes de migrar una base versión 1 se crea un archivo de backup único junto al
original, con nombre `<base>.schema1-<uuid>.bak`. Se emplea
`sqlite3.Connection.backup`, incluyendo commits del WAL, y
se verifica su integridad antes de cambiar el esquema. La copia usa una conexión
de lectura separada de la transacción que reserva la migración, evitando que el
backup espere indefinidamente a su propia escritura. El backup se conserva si
la migración falla. Un fallo o terminación abrupta revierte la transacción de
SQLite al reabrir; no se debe editar el marcador manualmente.

Para crear otro backup o restaurarlo, indicar rutas explícitas fuera del repo:

```bash
jobsearch database backup --source /datos/applications.sqlite3 --output /backups/copia-nueva.sqlite3
jobsearch database restore --source /backups/copia-nueva.sqlite3 --output /recuperacion/applications.sqlite3
```

Ambos comandos exigen que el destino no exista y no inicializan/migran el origen.
No reemplazan una base abierta. No copiar solo el `.sqlite3` mientras hay WAL
activo; una exportación CSV/JSON tampoco sustituye el backup de todo SQLite.

Rollback a la versión anterior:

1. Detener todas las instancias y conservar el directorio actual completo.
2. Restaurar el backup **previo a la migración** a un directorio nuevo con el
   segundo comando. Si solo existe un backup de esquema 2, eso no lo convierte
   en esquema 1: no hay downgrade destructivo implementado.
3. Verificar `PRAGMA integrity_check`, marcador de versión 1 y registros antes
   de usarlo. Las pruebas comparan IDs, JSON, notas, estados y fechas originales.
4. Ejecutar el código anterior a Fase 3 en un checkout separado, con
   `JOB_SEARCH_ASSISTANT_HOME` apuntando al directorio recuperado. Copiar también
   las copias conservadas de perfil/ajustes; el backup SQLite no incluye sus JSON.
5. Mantener la base versión 2 para recuperar manualmente cambios posteriores al
   backup. No abrirla con código antiguo, que sobrescribía su marcador de versión.

Los archivos contienen datos privados completos y no están cifrados. Los nuevos
backups se crean con permisos restrictivos donde el sistema los soporta; en Windows
revisar las ACL. Retención, cifrado, limpieza automática y un timer de backups no
forman parte de esta fase.

## Evidencia y límites de validación

Las pruebas utilizan perfiles, respuestas ATS y bases sintéticas temporales.
Cubren migración, rechazo de versión, fallo y salida abrupta, dos escritores,
reinicio, procedencia, elegibilidad adversarial, explicación determinista,
históricos, CLI, métodos GUI sin display y CSV/JSON. La evidencia de comandos,
conteos y CI Windows/Ubuntu del commit publicado se registra en el PR.

Verificación local tras las correcciones: Python 3.12.14, **159 pruebas
unittest** y **159 pytest + 347 subtests**; Python 3.10.22, **159 unittest**;
compilación, `pip check`, CLI help y preparación Linux headless: aprobados.
El PR conserva los resultados remotos y el veredicto de revisión independiente.

La revisión independiente identificó seis grupos de fallos de elegibilidad:
excepciones de México, alcance de preferencias, permisos de otros países,
condiciones adicionales ocultas, experiencia específica y negación de modalidad.
Las regresiones también cubren menciones repetidas de un requisito y denegaciones
de candidatura/disponibilidad. Se corrigieron sin debilitar aserciones anteriores.
El algoritmo histórico se comparó adicionalmente con la versión integrada en
Fase 2 para 90 combinaciones sintéticas, sin diferencias.

Se intentó consultar `docs.python.org/3/library/sqlite3.html` y
`sqlite.org/backup.html` desde este Cloud: ambos accesos devolvieron rechazo 403
del túnel proxy. No se cambió la política de red, TLS o CA. El comportamiento
se verificó con SQLite local y pruebas offline; no se afirma conectividad ATS,
prueba gráfica interactiva, despliegue o auditoría de Claude.

Tras revisión e integración de este PR, la Fase 4 necesitará autorización nueva
y podrá reutilizar las identidades/snapshots. Aquí no se implementan CV,
borradores, envío, notificaciones, scheduler ni cambios en PizzaLab.
