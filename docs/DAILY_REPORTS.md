# Reportes diarios privados y entrega a Work

Depende del hardening #11. Código preparado, no timer activo ni entrega externa.

```bash
jobsearch reports generate --config /privado/sources.json
jobsearch reports show 2026-11-04          # Contenido privado local explícito
jobsearch reports show 2026-11-04 --summary # Solo agregados, apto para revisar/exportar
```

Default 14:00 America/Mexico_City; `--at HH:MM --timezone IANA` permite otra política
antes de crear el registro schedule.json. La política queda fijada: cambiarla exige
un almacén/procedimiento nuevo, no reinterpretar reportes previos. Windows instala
la dependencia condicional tzdata; Debian debe tener datos IANA del SO.

Cada fecha debida tiene reports/AAAA-MM-DD/{report.json,report.md,manifest.json},
archivos 0600/directorios 0700 en POSIX, SHA256 y publicación por directorio. El archivo
es el registro idempotente: un reinicio después de publicar reutiliza los mismos
bytes/fecha y verifica integridad, sin segunda transacción SQLite o duplicación.
Los temporales propios incompletos no se consideran reportes. No se borra historia.

Ventana `[14:00 día anterior,14:00 fecha del reporte)`, con zona/UTC y extremo
exclusivo explícitos: no se pierden ofertas posteriores al informe anterior.
No generar fecha futura. --start-date permite recuperar un inicio explícito;
--max-reports 31 default limita catchup, remaining indica trabajo pendiente.
El próximo timer continúa fechas faltantes. Delayed y delay_seconds muestran
retraso; la hora de generación original se conserva al reutilizar.

## Contenido y temporalidad

Snapshot SQLite de lectura y CV verificados bajo el mismo automation.lock.
Historial de hallazgos toma referencias inmutables de automation_items/evaluations;
company/title/URL/fuente/fecha proceden de esas observaciones. La fecha de descubrimiento
usa started_at de la primera ejecución que la observó (no hay timestamp por ítem).
Reobservaciones se distinguen de nuevas ofertas; se usa la última evaluación dentro
de la ventana, sin reinterpretar snapshots históricos con el algoritmo actual.

URLs son metadata validada y enlaces pasivos; no se vuelven a consultar ni se afirma
vigencia independiente. Ofertas manuales conservan ese origen. Descripciones o
instrucciones remotas no se ejecutan; Markdown escapa HTML/texto y enlaces inválidos
se omiten. Prioridad alta/media, elegibilidad pendiente y rechazos conservan motivos.
Remote/Global/Americas no acreditan contratación legal desde México.

CV: versión/SHA/idioma/vacante/revisión/integridad y evidencia pendiente, sin contacto,
texto completo de CV o cover. Maestros y documentos se verifican con ResumeStore.
Estado actual y totales se etiquetan al momento de generar; en un catchup no se
inventan estados que el tracker tenía en una fecha pasada. Actividad diaria usa
los eventos con timestamps/revisión y no los confunde con acumulados.

Borrador, pendiente de aprobación, autorización local, simulación, applied manual,
seguimiento/entrevistas/outcomes/próxima acción están separados. El sistema no tiene
sender ni recibos de envío externo: **confirmed_real_submissions=0**. Un recibo de
simulación es local y submitted=false. Estado applied solo registra al usuario.
No se preparan/aprueban hechos profesionales automáticamente.

Operación: último run, fuentes configuradas/errores/pausas/duplicados, espacio libre
y último bundle verificado. Un backup con hashes válidos no garantiza que cubra
escrituras posteriores. JOB_SEARCH_ASSISTANT_BACKUPS permite el almacén externo.
Falta de backup o integridad fallida son visibles, no se inventa un respaldo.
Generate imprime solo fechas/resumen; show sin --summary solicita detalles privados.
Antes de compartir incluso el resumen revisar audiencia, fechas y patrones de actividad.

## Estado real de entrega

Generated/stored describen artefactos locales. delivered=false significa ausencia
de comprobante de entrega externa; read=false es ausencia de recibo de lectura,
no prueba de que nadie haya leído un archivo local. No existe transporte activado,
publicación, correo, Telegram, Drive o API de append a chats.

Investigación oficial (consulta Cloud 5 nov, fecha local de misión 4 nov 2026):

- [Scheduled tasks](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt)
  permite tareas y notificaciones en cuentas elegibles. No establece acceso al LXC
  privado ni un receptor arbitrario de reportes desde Debian.
- [ChatGPT Work y Codex](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex)
  describe experiencias Cloud/local; no documenta para esta aplicación una API de
  agregar mensajes al chat personal Work existente.
- [Local work sync y seguridad](https://help.openai.com/en/articles/20001548-agent-security-and-local-work-sync-in-chatgpt)
  exige computadora/conexiones/permisos adecuados; no prueba un puente configurado
  hacia un LXC Debian 12 sin interfaz.
- [Conversation state API](https://developers.openai.com/api/docs/guides/conversation-state)
  y [automations de Agents API](https://developers.openai.com/api/docs/guides/agents-api/sessions/automations)
  son recursos de API; no equivalen a historial ChatGPT Work personal. No se invocaron.

Se observaron herramientas oficiales de tareas/Pages disponibles, sin leer cuentas
personales ni crear automatizaciones. No existe acceso verificado desde esas tareas
al futuro almacén PizzaLab. Un conector Drive privado requeriría fuente/acceso y
escritura autorizados que aquí no existen. No crear un sustituto arbitrario.

Fallback completo: generar localmente y consultar por consola/SSH privado ya
autorizado en el host, o transferir el agregado mediante un canal privado revisado.
No abrir dashboard/puerto público, túnel nuevo o enlace público. Entrega Work sigue
**no configurada/no verificada**; su ausencia no bloquea reportes locales.

## Verificación manual

- [ ] Hora/zona y timer del host real; generar antes/después de 14:00.
- [ ] Una fecha, mismos bytes al repetir; JSON y Markdown legibles/ATS links seguros.
- [ ] Apagar durante dos fechas, recuperar sin duplicar y revisar delayed/remaining.
- [ ] Confirmar exclusiones, CV/evidencias, estados actuales frente a actividad diaria.
- [ ] Cero envíos confirmados; applied manual/simulado separados.
- [ ] Probar backup corrupto/disco lleno en datos sintéticos, sin publicar información.
- [ ] Comprobar privacidad/ACL y mecanismo Work real antes de afirmar entrega/lectura.
