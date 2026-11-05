# Backups conjuntos, recuperación y retención sin borrado

```bash
jobsearch storage backup --output /privado/backups/FECHA-ID --config /privado/sources.json
jobsearch storage verify-backup /privado/backups/FECHA-ID
jobsearch storage restore --source /privado/backups/FECHA-ID --output /privado/home-nuevo
jobsearch storage inventory --retention-days 90 --keep-backups 7
```

Home, CV/evidencias/manifiestos/versiones, perfil/ajustes/sources, reportes y logs
opcionales se capturan junto a SQLite. Config externa de fuentes se copia sin
cambiar permisos del origen; runtime.env seguro puede regenerarse desde layout,
no contiene secretos. Evidencias originales importadas ya están copiadas por hash
en resumes/evidence. No se copia recursivamente backups ni locks; estado HTTP,
candidaturas, evaluaciones e historial están dentro de SQLite.

API SQLite backup incluye commits WAL, no una copia del principal en vivo. La copia
exclusiva se sella DELETE antes de congelar inventario/hashes; el origen conserva
su journal_mode y puede tener conexión abierta. Mantener coherencia de operaciones:
RunLock compartido para automatización, reportes, bundles y comandos CLI que pueden
crear perfil o migrar, incluso list/export/doctor. GUI oficial mantiene ese lock
durante la ventana: cerrarla antes de búsqueda/backup en el mismo home. Direct APIs,
clones independientes o escritores externos requieren que el caller coordine o los
ponga en mantenimiento; no se afirma una transacción distribuida sobre ellos.

Se comprueban huellas de documentos/config antes y después, cambios invalidan el
snapshot. El manifiesto registra versión, fecha, esquema e inventario exacto SHA256.
Publicación exclusiva en destino nuevo; verificador de solo lectura exige inventario
completo, archivos privados/sin links, hashes, integridad y claves foráneas SQLite.
No se afirma frescura respecto a escrituras posteriores ni autenticidad ante un
administrador que pueda falsificar archivo y manifiesto. Datos en claro: para un
respaldo externo definir cifrado y custodia de claves con el operador; no añadir
una plataforma o dependencia sin necesidad y autorización.

Se estima espacio requerido con margen antes de copiar; errores de disco/permisos
no publican un bundle válido. Solo se limpian los temporales exclusivos de la
invocación fallida; no se eliminan datos reales previos. Directorios0700/archivos 0600
POSIX independientes de umask; Windows requiere ACL privada. Backups versionados
no se sobreescriben. Se verifica antes de exponer un home restaurado.

Restore a destino **nuevo** conserva configuración/documentos/reportes y utiliza
restore_backup para revocar autorizaciones antiguas y activar source_review_required.
No reemplaza SQLite abierta. Revisar fuentes: un backup antiguo no conoce cooldowns
posteriores; no borrar restricciones para reanudar antes. Los plazos conocidos siguen
vigentes y los no representables no se liberan automáticamente. Las aprobaciones
necesitan nueva revisión/revisión de CV; estados terminales no se reactivan.
Registro restore.json local separa restauración de cualquier envío (submitted=false).

Rollback de código es diferente de restaurar datos. Antes de migrar conservar copia
compatible de esquema, CV/evidencias/config. No alterar schema_version ni usar código
viejo con esquema nuevo. Restaurar copia anterior puede omitir cambios posteriores;
conservar el home actual y reconciliar diferencias manualmente, nunca pérdida silenciosa.
Procedimiento operativo/activación en [DEPLOYMENT](DEPLOYMENT.md).

## Retención L-05

Inventory es **solo lectura/dry_run=true/deleted=0**. Calcula tamaños por categoría y
backups por fecha. Default 90 días y al menos 7 respaldos recientes protegidos; propone
candidatos antiguos después de ambos criterios. latest siempre se conserva. No borra
SQLite, snapshots/evaluaciones, CV, evidencia, candidaturas o reportes referenciados.
Logs/artefactos pueden archivarse mediante procedimiento privado del operador, no
una tarea automática de esta entrega. La estimación de crecimiento queda unknown
hasta comparar inventarios reales sucesivos; no inventar tasas por día.

Home/backups por defecto, o JOB_SEARCH_ASSISTANT_BACKUPS para ruta externa privada.
JOB_SEARCH_ASSISTANT_LOGS permite capturar logs privados externos. Journal systemd
es administrado por el SO: configurar retención/ACL allí antes del piloto, sin
exportarlo automáticamente como reporte. La aplicación solo emite eventos redactados.

Inventario corrupto/links/permisos inseguros se rechazan para revisión. Guardar las
salidas en un canal privado; nombres de backups y patrones temporales también revelan
actividad. La ejecución no destruye ni compacta información por una edad configurada.
