# Hardening de Fase 6 — evidencia y límites

Base: PR #10 integrado, main `cfa6a4d974ce129a2bc8aeeb4ee4d53b6afc44f7`, CI74
satisfactorio. Esta entrega propone cambios; no afirma integración o despliegue.
Los hallazgos suministrados de Claude se reprodujeron con datos sintéticos propios.
No se invocó a Claude para esta implementación.

| Hallazgo | Reproducción y cambio | Evidencia |
| --- | --- | --- |
|M-01|Permiso México más exclusividadEEUU antes high_priority95; ahora contradicción/inelegibilidad conservadora por contexto, sin habilitar otro rol|test_geographic_hardening, test_matching; matching_v3, históricos intactos|
|M-02|Cancelar tras200 antes penalizaba también proveedor sin consultar|test_source_hardening, test_automation; control local neutral,429/5xx reales conservados|
|M-03|umask022 antes home0755/JSON/SQLite0644|test_private_storage; directorios0700/archivos0600, tipos/owner/links/auxiliares|
|M-04|Runtime Telegram y productores activos aunque opt-in|test_telegram_retirement, test_phase5_interfaces; módulos/flag eliminados, historia inalterada y triggers de retirada|
|L-01|Retry-After enorme requiere preservar restricción sin overflow|test_source_hardening/source_recovery; texto decimal durable, suspensión manual, digest/auditoría, restore en cuarentena|
|L-02|30 casos debug adicionales permitían preparar diff|test_claude_review; secrets/vars/runner.debug rechazados antes de preparación|
|L-03|Python3.11 faltaba|CI define Windows/Ubuntu×3.10/3.11/3.12/3.13; confirmar8/8 en SHA delPR|
|L-04|running legítimo se diagnosticaba mal|test_operational_health; activo/demorado/abandonado/antiguo/proveedor degradado separados|
|L-05|Crecimiento sin política explícita|Entrega B separada: inventario/simulación, sin borrados automáticos|
|I-03/I-05|Restore antiguo puede perder límites; worker vivo no admiteclose|Revisión explícita tras restore; no ignorar plazos conocidos; worker_cleanup_failed si sobrevivekill|

## Revisión del límite privado

Se realizó investigación independiente previa al parche y revisión independiente
read-only de un candidato. Esta detectó dos regresiones: restore alteraba permisos
del origen externo y perfiles válidos de más512KiB podían cargar valores por defecto.
Tres casos RED las reprodujeron; el autor corrigió ambos límites y pasó114 pruebas
focales con188subtests. No se atribuye una segunda revisión a ese revisor.
No se publican artefactos temporales de seguridad ni datos personales en Git.

Aperturas SQLite distinguen almacenamiento gestionado e imports externos de solo
lectura. La protección POSIX se verificó con umask000/022/777, WAL/SHM existentes,
backup/restore, symlinks/hardlinks y rechazo de owner simulado. No se realizó ataque
crossUID real ni validación de ACL nativa Windows en Cloud. Un administrador o el
mismoUID que controle todo el almacén sigue pudiendo falsificarlo; no es cifrado.

## Pruebas y validación

Los resultados finales locales, revisión funcional y CI remoto de cada SHA se
registran en el PR. Las pruebas no dependen de servicios externos. Se conservaron
los launchers y ambas suites; los tests del transporte retirado fueron sustituidos
por controles de ausencia/migración/historial, no por una simulación de entrega.
No afirmar que un run sin fuentes demuestra conectividad, ni que unit tests
validan Debian12/LXC/systemd en producción, GUI visual, Telegram, Claude o Work.

Para rollback: preservar backup previo al esquema5 y documentos/config coherentes;
restaurar a destino nuevo con código compatible, nunca bajar el marcador. Restore
revoca aprobaciones y mantiene revisión de fuentes. No eliminar historial real,
locks, cuotas ni restricciones para forzar recuperación.


## Corrección preproducción R-01 — 2026-11-05

HEAD comprobado antes del cambio: #11 en 6b915569a0224613680bc4f3354d36814104b4e1;
#12 en 50a2b157748276a555a3a28a06580b3979a816b5, ambos abiertos y sin integrar.
La auditoría suministrada de Claude se comprobó con datos sintéticos propios.

Causa raíz: el fullmatch de ubicación no aceptaba only dentro de paréntesis,
US-based, listas de países ni el país único del ATS. La segmentación por punto y
coma perdía el contexto de `Remote; US-based`. Evaluar cada ubicación por separado
también convertía una lista que incluía México en una exclusión falsa.

Se reconstruye cada campo de ubicación conservando sus spans/offsets/procedencia;
una gramática acotada reconoce esas etiquetas. Las alternativas México suprimen
solo exclusividad inferida; only y restricciones del cuerpo siguen excluyendo o
produciendo contradicción. No se convierte una mención incidental US en exclusión
ni una ubicación México en permiso de contratación. Parser del cuerpo preservado.

RED: 31 fallos de subTest. Los siete ejemplos R-01 se probaron como JobPosting y
NormalizedJob, con/sin permiso México, más controles positivos y contradicciones.
La regresión de caché conserva el snapshot matching_v3 y genera una evaluación
matching_v4 independiente al observar de nuevo el mismo contenido. Esta versión
nueva evita reutilizar una prioridad alta v3 afectada; no migra ni reinterpreta
históricos automáticamente. Resultados GREEN/suites/CI del SHA final en el PR.

Checklist manual: revisar evidencia de exclusión y contradicción de las siete
etiquetas, confirmar listas US/México permitidas sin exclusividad explícita y
verificar nueva evaluación v4 junto al histórico v3. No activar fuentes o servicios.

La revisión interna independiente de0a3b96c encontró una regresión adicional:
dos etiquetas completas dentro de un mismo campo (US; Canadá) perdían su exclusión.
Se reprodujeron seis subtests RED en ambos modelos; se conserva ahora cada span
reconocido cuando el campo reúne varias etiquetas y no incluye alternativa México.
La revisión corresponde a ese SHA, no constituye una nueva revisión de Claude.


## R-01b y N-03 — 2026-11-05

Base comprobada: #11 en 875585782d9672ae0879e2c415b3ca7467b9db37 y #12
en 74c66adcdb4529dcea4197371d534490ce8f0e97; ambos abiertos, sin integrar.
Los hallazgos suministrados de Claude se comprobaron localmente con datos sintéticos.
No se ejecutó una nueva revisión de Claude ni hubo despliegue o consultas ATS.

R-01b: la gramática del cuerpo exigía people antes de only. Por eso This role/
position is US only, Location: US only, Eligibility: United States only y Hiring
in the US only no proporcionaban evidencia negativa, aunque podían contradecir
un permiso México aplicable. Además fallaban Remote: North America (US only) y
Remote (US Only - EST), por exigir una etiqueta completa sin región/huso adicional.

N-03: los siete formatos reportados como preexistentes no estaban reconocidos por
la gramática de ubicaciones (orden país-remoto, separadores pipe/raya, ciudad/estado
or Remote, nombre completo de país y español) o por el orden Only open to candidates.
Se amplían esos formatos de forma acotada, sin interpretar toda mención US como
residencia. No se incorpora geocodificación ni un parser general de lenguaje natural.

La condición country-only genérica exige contexto de contratación/puesto o campo
de ubicación. Conserva alcance del puesto, negación y excepciones México. Oficinas,
clientes, beneficios y predicados de horario no excluyen la residencia. Un EST
adyacente a una exclusividad US explícita no la borra; EST por sí solo no confirma
residencia. Las condiciones may/might/could/if se conservan como unknown y requieren
revisión, incluso cuando exista un permiso México potencialmente incompatible.

RED de las variantes requeridas: 56 subtests (28 R-01b y 28 N-03), en JobPosting y
NormalizedJob, con/sin permiso México. El primer ensayo mostró 58: dos expectativas
nuevas sobre un horario EST obligatorio se ajustaron al contrato previo de requisito
no interpretado: revisión pendiente, sin exclusión de residencia; no cambió ese parser.
Luego se reprodujeron 16 casos condicionales y 8 decoraciones horarias adicionales.
Los controles positivos/adversarios se conservan junto a la evidencia original,
offsets y procedencia ATS. Los resultados GREEN/suites/CI del SHA final están en PR.

matching_v7 es la versión final: aun con la gramática corregida, automation_observations
reutilizaba un high_priority v4 para los mismos inputs. Una prueba RED lo confirmó.
La regresión de persistencia guarda legacy_v1/v2/v3/v4, compara los bytes de sus
snapshots antes/después, crea una evaluación v7, reinicia el store y vuelve a
observar sin cambios: una vacante, cinco evaluaciones (cuatro históricas y la actual),
misma ID v7 reutilizada y ninguna reescritura histórica. No se migra masivamente.

Riesgo residual: reglas acotadas, sin certificación jurídica o comprensión general.
Las frases no reconocidas y datos esenciales desconocidos requieren revisión;
no se presume permiso México de Remote/LATAM ni de residencia del candidato.
No se afirma validación de producción en Debian 12/LXC o una nueva auditoría Claude.

Checklist antes de integrar: revisar los ejemplos de cuerpo y ubicaciones, sus
controles de contexto/negación/alternativas, las evidencias en los dos modelos,
la coexistencia histórica v4/actual v7, y CI 8/8 de ambos HEAD. Incorporar el nuevo
#11 a #12 solo por merge, conservar los diez commits propios y comprobar el diff.
No retargetear, fusionar PRs ni activar servicios dentro de esta corrección.


La revisión interna independiente del candidato 8bb2695 (v5) detectó tres errores
de contexto: excepción/alternativa México tras coma, condición if pospuesta y
predicados de seguro médico/working hours mal interpretados como residencia.
Se reprodujeron 40 subtests RED en ambos modelos/con-sin permiso México. La solución
conserva la cola para excepciones/condiciones inmediatas y exige un predicado de
contratación, una cópula del puesto o una etiqueta geográfica; role por sí solo no
basta. Las variantes desconocidas/condicionales siguen requiriendo revisión.
Otros cuatro subtests RED comprobaron que customer support puede ser el nombre
del puesto restringido, sin equivaler a una mención incidental de sus clientes.
La cópula del puesto conserva esa restricción; no se amplió el gate a cualquier
mención de role. Todos estos escenarios tienen aserciones de estado y clasificación.

Los candidatos v5 (8bb2695) y v6 (249001e) fueron publicados antes de cerrar las
revisiones. Las observaciones con falsos descartes se reutilizaban aun corrigiendo
el parser: pruebas RED para cada caché lo confirmaron. Por eso la versión final
es v7: conserva también snapshots v5/v6, además de legacy_v1/v2/v3/v4. No se
reescribieron commits públicos ni se forzó el historial.

La revisión de seguimiento de 8bb2695..249001e detectó una alternativa México
tras cierre de paréntesis perdida por el conector anclado. Doce nuevos subtests
RED reprodujeron alternativas/condiciones en ese límite. Se admite solo un cierre
inmediato antes del conector. El seguimiento local verificó el parser corregido
(SHA-256 6489ab5a0c7abf017239680445da02f43bebc1ed115ebf66f61294b35198293a),
90 tests focales y controles que no cruzan cláusulas independientes: ningún
Critical/Important pendiente en ese ajuste. También se corrigió la colocación de
aserciones al insertar el test, conservando todas las anteriores. La revisión no
cubre cambios posteriores de versión/documentación/caché ni constituye Claude.

Validación local final del parser: 434 pruebas unittest, sin fallos (un skip exclusivo
de Windows en Linux); pytest: 433 pruebas y 988 subtests, sin fallos, el mismo skip.
pip check, compileall, ruff E9/F sobre src/tests y git diff --check satisfactorios.
Los resultados y enlaces de CI por HEAD se registran en los cuerpos de #11 y #12.
