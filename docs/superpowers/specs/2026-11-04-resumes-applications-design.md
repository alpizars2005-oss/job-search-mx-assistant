# Diseño de Fase 4 — CV y candidaturas locales

## Alcance autorizado

Implementar currículums maestros verificables ES/EN, versiones adaptadas, evidencia,
exportación ATS, SHA-256 e historial; borradores vinculados a empresa/vacante/CV,
tracker, transiciones, deduplicación y aprobación específica de un solo uso.
No implementar envíos externos reales. `applied` es únicamente un registro local.
`DRY_RUN=true` y `AUTO_SUBMIT=false` son política obligatoria.
Preservar CLI/Tkinter, perfiles JSON, SQLite, exportaciones e idiomas; probar
migración, reinicio, recuperación, concurrencia entre procesos y compatibilidad.
Datos personales fuera del repositorio, sin información privada en logs.
Terminar con PR independiente a main, sin merge ni Fases 5–6, Telegram, Claude o PizzaLab.

## Base comprobada

PR #8 integrado en `67c10918295a2b30abe9ffd9d5b03f3ec5f24f16`; CI de main,
ejecución 69 `41932682397`, completed/success en seis combinaciones Windows/Ubuntu
y Python 3.10/3.12/3.13. Rama `codex/phase-4-resumes-applications` desde origin/main.
Baseline local: 159 unittest; 159 pytest +347 subtests, aprobados.

## Decisiones del desarrollador

Se conserva Python 3.10+, biblioteca estándar y un único tracker SQLite. Frente
a generación libre con modelos o plataformas externas, se elige composición
determinista de hechos aportados por el usuario, porque permite comprobar que no
se inventan empleos, tecnologías o certificaciones. La adaptación selecciona y
ordena hechos; no convierte proyectos en experiencia profesional ni traduce datos
ausentes. El usuario puede corregir estas decisiones mediante el trabajo normal
de revisión; la misión autoriza ejecución autónoma sin confirmaciones intermedias.

TXT UTF-8 y DOCX OpenXML simple serán los formatos iniciales. DOCX se genera con
zipfile y XML escapado, sin macros, recursos externos, columnas o imágenes. No se
agrega un motor PDF ni dependencias de oficina. Compatibilidad ATS significa
estructura textual convencional; no promete certificación de todos los proveedores.

Un maestro JSON separado del perfil histórico contiene identidad, traducciones
ES/EN de hechos categorizados y referencias a evidencia con hash. La evidencia
se copia a almacenamiento privado; no se ejecuta ni se descarga. Solo hechos
respaldados y atestiguados explícitamente pueden usarse. La atestación del usuario
permanece distinguida de verificación independiente de la verdad del documento.

Maestros/versiones son inmutables y direccionados por contenido. Los bytes del
CV y manifiesto se verifican al leer, revisar, aprobar y consumir autorización.
La modificación de evidencia o un documento invalida su uso. Una escritura
interrumpida puede dejar un archivo privado sin referencia; nunca se confirma
metadata que apunte a un documento aún no publicado atómicamente.

## Borradores y autorización

Se amplía esquema 2→3 sin alterar filas históricas. La creación de una candidatura
reutiliza `applications` y registra una identidad única de vacante; versiones del
borrador, revisiones, eventos y autorizaciones conservan snapshots. La versión 1
también migra secuencialmente hasta 3 en una transacción y con backup previo del
esquema de origen; bases nuevas no requieren backup sin datos anteriores.

El workflow del borrador es draft→reviewed→approved→simulated. La edición real
crea otra revisión, vuelve a draft e invalida autorizaciones; una edición idéntica
no reescribe el historial. La simulación no cambia automáticamente el tracker a
applied. Las transiciones del tracker se verifican para candidaturas gestionadas;
los registros manuales anteriores conservan su API y datos.

La CLI difiere construcción/verificación del almacén hasta entrar al guard
transaccional, incluida composición automática de texto. Una adopción legacy
reconcilia el destino actual con el tracker y conserva la fila anterior como evento;
si ese registro ya se aplicó a otro destino, se rechaza sin cambiar su historia.

La revisión muestra un digest de empresa, identidad/snapshot de vacante, versión
y SHA del CV, contenido exacto del borrador y número de revisión. Aprobar exige
ese digest concreto. La autorización tiene ID aleatorio, snapshot y estados
active/invalidated/consumed. Su consumo se serializa en SQLite y solo devuelve
un recibo local `submitted=false`; no existe sender. Consumo repetido o política
insegura falla. CV, evidencia, vacante, versión o contenido cambiado bloquean el
consumo e invalidan la autorización de forma persistente.

El digest de vacante incluye todos los campos normalizados salvo `retrieved_at`:
una nueva observación idéntica no cambia el contenido aprobado. Las fechas,
resultados, notas y próximos pasos internos no forman parte de un texto externo
aprobado. Pasar el tracker a applied o a un estado posterior invalida permisos
pendientes y sigue siendo exclusivamente registro manual.

## Interfaces y límites

La CLI permite importar maestro, listar/verificar/adaptar/exportar versiones,
crear/editar/ver/revisar/aprobar/simular borradores e inspeccionar historial y
seguimiento. Una importación manual explícita de vacante reutiliza modelos
normalizados sin red ni scraping para que el flujo también funcione offline.
Las fuentes ATS anteriores permanecen opt-in. GUI/tracker y exportaciones previas
se conservan; errores de transiciones gestionadas se muestran sin traceback privado.

La aprobación confirma contenido local, no elegibilidad jurídica ni autenticidad
independiente de credenciales. El propietario del almacenamiento local controla
la evidencia; no se promete resistencia a un administrador que falsifique SQLite
y todos sus archivos. No hay borrado automático de históricos ni limpieza de
documentos huérfanos. La operación continua corresponde a fases posteriores.
