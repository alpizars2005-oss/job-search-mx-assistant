# CV, candidaturas y tracker — Fase 4

Esta fase agrega documentos privados, borradores revisables y autorizaciones para
una **simulación local**. No existe un sender ni se envían CV, correos o candidaturas.
Registrar `applied` conserva su significado de seguimiento manual.

Base comprobada: PR #8 integrado en `67c1091`, CI de main
[ejecución 69](https://github.com/alpizars2005-oss/job-search-mx-assistant/actions/runs/41932682397),
seis combinaciones Windows/Ubuntu aprobadas. La implementación reutiliza Python
3.10+, SQLite, CLI/Tkinter y biblioteca estándar.

## Almacenamiento y política

Los archivos se guardan en `JOB_SEARCH_ASSISTANT_HOME/resumes`, fuera del checkout:

- `masters`: maestros JSON inmutables y direccionados por contenido.
- `evidence`: copias de los documentos que respaldan los hechos declarados.
- `documents`: bytes exactos de cada TXT o DOCX, identificados por SHA-256.
- `versions`: manifiestos de contexto, selección de hechos, idioma, formato y hashes.

Las evidencias se copian; mover el archivo de entrada no rompe el snapshot privado.
Cambiar las copias almacenadas sí provoca fallo de integridad. El almacén puede
copiarse a otro directorio y verificarse sin rutas absolutas al original.

Los nuevos comandos y las mutaciones del workflow exigen `DRY_RUN=true` y
`AUTO_SUBMIT=false`; esos son los defaults cuando faltan variables. Un valor
inseguro o mal formado produce error, sin consumir una autorización. La API de
documentos es local y tampoco tiene una ruta de envío. No hay un modo de activar
envíos en esta fase.

Linux, opcionalmente explícito:

```bash
export JOB_SEARCH_ASSISTANT_HOME=/ruta/privada/jobsearch
export DRY_RUN=true
export AUTO_SUBMIT=false
```

PowerShell:

```powershell
$env:JOB_SEARCH_ASSISTANT_HOME = "C:\Users\TU_USUARIO\Documents\JobSearchPrivate"
$env:DRY_RUN = "true"
$env:AUTO_SUBMIT = "false"
```

No usar un directorio dentro del repositorio. Se rechazan symlinks, rutas de
documentos no regulares y URLs de evidencia; no se descargan recursos. La
publicación exclusiva de archivos requiere enlaces duros, habituales en NTFS y
los sistemas de archivos Linux locales. No se promete soporte de FAT ni de
almacenamientos de red con semántica de bloqueo/publicación incompatible.
Los archivos se crean con permisos POSIX restrictivos; en Windows revisar ACL.
No se cifran documentos ni snapshots automáticamente.

## Maestro verificable en español e inglés

El maestro es JSON separado de `profile.json`; no se sustituye el perfil de
matching ni se convierte YAML silenciosamente. Un ejemplo de estructura es:

```json
{
  "schema_version": 1,
  "candidate": {"name": "Persona sintética", "contact": ["synthetic@example.test"]},
  "evidence": [{"id": "proof", "path": "evidence.txt", "sha256": "HASH_SHA256_DEL_ARCHIVO"}],
  "claims": [{
    "id": "project-python",
    "kind": "project",
    "text": {"es": "Proyecto personal documentado con Python.", "en": "Documented personal Python project."},
    "evidence_ids": ["proof"],
    "attested": false
  }]
}
```

Cada hecho tiene ID estable, categoría (`experience`, `project`, `certification`,
`education`, `skill`), textos ES/EN, evidencia y atestación explícita. Los hechos
sin respaldo o `attested=false` no se usan al generar. Seleccionarlos expresamente
también se rechaza. Una atestación representa revisión humana del material; un
hash confirma integridad, **no demuestra por sí solo que la afirmación sea cierta**.

Las rutas de evidencia se resuelven respecto al JSON de entrada. Para obtener el
SHA requerido puede usarse `sha256sum evidence.txt` o, en PowerShell,
`(Get-FileHash evidence.txt -Algorithm SHA256).Hash.ToLower()`.

No se traducen datos faltantes ni se completan años, empresas, títulos o métricas.
La generación conserva literalmente los hechos seleccionados y sus categorías:
un proyecto personal nunca se transforma en empleo. El nombre/contacto vienen de
la declaración del usuario; los titulares libres opcionales quedan como metadata
del maestro y no se renderizan como credenciales sin evidencia.

Los límites son 512 KiB de JSON, 200 hechos, 100 evidencias, 10 MiB por evidencia
y 100 MiB en total. Se validan tipos, IDs únicos, referencias, caracteres, tamaños,
claves y hashes. No se interpreta ni ejecuta el contenido de un PDF u otro adjunto.

```bash
jobsearch resumes import /ruta/privada/master.json
jobsearch resumes list
```

Copiar los ejemplos sintéticos fuera del checkout antes de probarlos. No usar sus
datos como experiencia real. Antes de cambiar `attested` a `true`, revisar el hecho
y su evidencia correspondiente.

## Vacante y versión adaptada

Se pueden usar las vacantes de `discover --save`. Para trabajar sin red también
existe importación manual explícita de JSON con los campos históricos de JobPosting:

```json
{
  "title": "Puesto sintético",
  "company": "Empresa sintética",
  "location": "Ubicación no confirmada",
  "url": "https://example.test/jobs/synthetic",
  "description": "Descripción sintética; no confirma contratación desde México."
}
```

```bash
jobsearch vacancies import /ruta/privada/job.json
jobsearch vacancies list
jobsearch resumes tailor MASTER_ID --vacancy 1 --language es --format docx --claim project-python
jobsearch resumes verify VERSION_ID
jobsearch resumes export VERSION_ID /ruta/privada/cv-es.docx
```

La importación manual no sigue URLs, abre navegador ni llama a fuentes externas.
Conserva procedencia `manual_json`, identidad determinista y estado no verificado;
usa el mismo motor de matching. Los lectores ATS mantienen sus controles previos.

La adaptación se hace por selección y orden de hechos válidos, dentro de sus
categorías; `--claim` es repetible. Sin selección se incluyen los hechos respaldados
y atestiguados. La vacante aporta contexto de destino, no nuevas cualificaciones.
La versión queda ligada al snapshot de esa vacante y al maestro utilizado.

El mismo contenido/contexto produce el mismo ID y conserva la fecha de primera
publicación. El SHA del documento identifica sus bytes exactos; el ID de versión
también enlaza maestro, idioma, formato, selección y vacante. DOCX usa ZIP sin
compresión y timestamps fijos para conservar bytes entre plataformas.

TXT es UTF-8 y DOCX contiene párrafos de una columna, sin macros, imágenes o
relaciones externas. Ambos preservan texto seleccionable. La estructura es simple
para ATS; no se afirma certificación con todos los proveedores ni validación
gráfica en Word/LibreOffice. No se genera PDF en esta entrega. La extensión del
destino debe coincidir con el formato y el archivo de destino no debe existir.

## Borrador, revisión y aprobación exacta

```bash
jobsearch candidacies create --vacancy 1 --resume VERSION_ID
jobsearch candidacies list
jobsearch candidacies show 1
jobsearch candidacies review 1
jobsearch candidacies approve 1 --digest DIGEST_MOSTRADO_EN_LA_REVISION
jobsearch candidacies simulate AUTHORIZATION_ID
jobsearch candidacies history 1
```

El borrador generado utiliza datos observados de empresa/vacante y los hechos del
CV verificado. `show` y `review` muestran contenido privado porque son acciones
explícitas de revisión; no compartir su stdout como un log público. Los listados
por defecto y los recibos no imprimen el CV o el contacto completo.
Un maestro sin hechos atestiguados puede producir un documento de identidad/contacto
sin cualificaciones; no permite componer un borrador factual automático.

`--content-file` permite aportar o editar texto manual; conserva exactamente lo
que suministre el usuario. No es un comprobador general de veracidad: cotejar todo
texto manual con el maestro antes de aprobar. No se ejecutan instrucciones de
vacantes o documentos. Los prompts AI anteriores siguen siendo opcionales y manuales.

El workflow es `draft → reviewed → approved → simulated`. Revisar muestra digest
y snapshot; aprobar exige ese digest vigente. La autorización enlaza empresa,
identidad/snapshot de vacante, ID/versión/SHA del CV, texto exacto y revisión. Tiene
un identificador aleatorio y estado `active`, `invalidated` o `consumed`.
`create` es idempotente: devuelve el ID existente sin sustituir su CV o borrador.
Para modificarlo se usa `edit` y se revisa de nuevo.

La simulación consume una vez en transacción y devuelve `submitted=false`,
`dry_run=true`, `auto_submit=false`. Un segundo proceso, reinicio o intento repetido
no reutiliza el permiso. El tracker no pasa automáticamente a applied.

```bash
jobsearch candidacies edit 1 --content-file /ruta/privada/revised.txt
jobsearch candidacies edit 1 --resume NUEVA_VERSION_ID
```

Una edición real crea revisión nueva y revoca permisos previos; volver al texto
anterior no recupera la autorización. Un no-op conserva historial. Cambiar vacante
exige un CV ligado al destino nuevo. Empresa, descripción, modalidad, URL,
procedencia y demás contenido normalizado forman parte del binding; solo
`retrieved_at` se excluye para no invalidar por observar de nuevo contenido idéntico.

La integridad de CV, manifiesto y evidencia se comprueba al revisar/aprobar/consumir.
Si falla, la revocación se confirma antes de devolver el error. No se monitorean
archivos en segundo plano: la comprobación ocurre al usar el workflow. Restaurar
los bytes después de una revocación no reactiva el permiso antiguo.
La inicialización del almacén y la generación automática quedan dentro del guard
transaccional; un error previo de ruta/documento no omite esa revocación.

## Tracker, fechas y resultados

Se reutiliza `applications`, con una candidatura por identidad de vacante y sin
duplicar la aplicación anterior. Revisiones, eventos y snapshots permanecen en
tablas separadas. Identidades distintas que ya pertenecen a otra aplicación se
rechazan para no fusionar dos historias silenciosamente.
Al cambiar destino o reparar una fuente actualizada, se conserva el par anterior
vacante/evaluación como historial y la evaluación actual queda explícitamente
pendiente. No se atribuye el score de otra vacante al destino nuevo.
Adoptar una fila legacy guardada puede reconciliar empresa/puesto/contenido con
su destino actual, conservando el original en historial; si ya registra applied
o un estado posterior para otro destino, se rechaza para no alterar su historia.

```bash
jobsearch candidacies update 1 --status interested --next-step "Revisar requisitos" --follow-up 2026-12-01
jobsearch candidacies update 1 --status applied --outcome "Registro manual de una acción realizada fuera de la app"
jobsearch applications list
jobsearch export --format json --output /ruta/privada/tracker.json
```

En candidaturas gestionadas, saved/interested permiten avanzar a applied,
rejected o withdrawn; applied permite screening/interview/offer/rejected/withdrawn;
screening permite interview/offer/rejected/withdrawn; interview permite
offer/rejected/withdrawn. Los estados terminales no retroceden. Repetir un estado
es idempotente. Los cambios anteriores de CLI/GUI llegan a esas mismas validaciones.
Los registros legacy sin candidatura conservan su API manual.

Pasar a applied o posterior revoca permisos pendientes, pero no envía nada.
Notas, resultado y próximos pasos son metadata interna; no modifican el contenido
externo aprobado. `follow_up_on` es fecha de calendario YYYY-MM-DD aportada por
el usuario, sin recordatorio automático ni zona horaria inferida. Eventos técnicos
guardan timestamps UTC. CSV/JSON anteriores conservan sus formatos; el historial
de candidaturas se consulta explícitamente mediante el comando nuevo.

## Esquema 3, backup y recuperación

Migración aditiva desde 1 o 2 con backup `.schemaN-UUID.bak` antes del primer DDL,
una transacción explícita y validación del marcador. Se mantienen registros,
duplicados, notas, estados, IDs, fechas y JSON históricos. Un fallo o terminación
abrupta revierte al esquema de origen. No se cambian versiones futuras desconocidas.

Antes de recuperar, detener todas las instancias y conservar el directorio actual.
El backup SQLite no incluye los archivos privados de CV. Para recuperar el conjunto:

1. Crear backup SQLite consistente con `jobsearch database backup`; no copiar solo
   el archivo principal si hay WAL.
2. Conservar también `resumes/` y los JSON de perfil/ajustes. Los documentos son
   inmutables y no se borran automáticamente; pueden copiarse después del snapshot
   SQLite. No editar archivos durante la copia y verificar su integridad.
3. Usar `jobsearch database restore --source BACKUP --output NUEVO_HOME/applications.sqlite3`;
   nunca sobrescribir la base abierta. Restaurar el almacén y JSON en NUEVO_HOME.
4. La restauración oficial revoca autorizaciones activas del backup y prepara
   revisión nueva: un backup antiguo no debe resucitar un permiso ya utilizado.
   Revisar otra vez antes de una autorización nueva. No recuperar mediante una
   copia manual del SQLite que omita este paso.
5. Configurar `JOB_SEARCH_ASSISTANT_HOME=NUEVO_HOME`, verificar versiones CV e
   historial y mantener el origen detenido. Dos copias independientes de una base
   no comparten un registro global de consumo.

Rollback del código a Fase 3 requiere su backup **de esquema 2**, restaurado en
destino nuevo, y un checkout separado de esa versión. El backup SQLite de esquema
3 no es un downgrade. Mantener la base y documentos nuevos para no perder cambios
posteriores; el código anterior no gestiona las nuevas tablas/archivos.

Una interrupción puede dejar blobs o temporales privados sin referencia; un
reintento verifica/publica correctamente y nunca sobrescribe un documento distinto.
No hay retención ni limpieza automática. Los backups contienen información privada
completa; protegerlos como el origen. No se promete resistencia a un administrador
que falsifique SQLite, triggers y todo el almacén.

## Validación y revisión manual

Las suites usan documentos, perfiles, HTTP y SQLite sintéticos en temporales, sin
servicios externos. El PR registra comandos, conteos, hallazgos corregidos y CI real
Windows/Ubuntu del commit final. La GUI se verifica con métodos headless; las nuevas
operaciones completas están disponibles en CLI y el tracker GUI conserva su uso.

Validación local final en Linux: **259 pruebas unittest** en Python 3.12.14 y
3.10.22; pytest **259 pruebas +523 subtests**, aprobados. Compilación, `pip check`,
Ruff E9/F, CLI help, preparación Linux y diff completo: aprobados. Los ejemplos
sintéticos importan correctamente y no generan hechos no atestiguados.

La revisión independiente verificó las correcciones de restauración de permisos,
atribución del tracker, snapshots de historial, rutas y guards de integridad de
CLI/adopción legacy. La comprobación final ejecutó **16 pruebas +19 subtests** y
**seis escenarios propios**. La evidencia de CI remota del HEAD publicado se
mantiene en el PR; no se deduce del éxito local. No se declara auditoría de Claude.

- [ ] Cotejar cada hecho ES/EN, categoría y evidencia; no usar proyectos como empleo.
- [ ] Abrir TXT/DOCX localmente y revisar texto seleccionable, acentos y formato.
- [ ] Verificar empresa, identidad de vacante, versión, SHA y contenido al revisar.
- [ ] Comprobar que editar CV/borrador o cambiar destino invalida el permiso anterior.
- [ ] Simular dos veces: únicamente la primera debe devolver recibo exitoso.
- [ ] Confirmar que registrar applied solo cambia seguimiento local.
- [ ] Probar backup del conjunto y restauración a destino nuevo, con revisión nueva.
- [ ] Revisar privacidad de archivos/ACL, exportaciones y stdout antes de compartir.

La Fase 5 requiere integrar este PR y una autorización nueva. No se instalaron
Telegram, Claude Code, scheduler o componentes de PizzaLab.
