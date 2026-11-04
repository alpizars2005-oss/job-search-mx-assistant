# Privacy

Job Search Assistant stores profiles, job descriptions, notes, and application history locally. No telemetry is included.

## Local paths

- Windows: `%APPDATA%\JobSearchAssistant`
- Linux: `$XDG_DATA_HOME/job-search-assistant` or `~/.local/share/job-search-assistant`

Set `JOB_SEARCH_ASSISTANT_HOME` to use another directory.

## Recommendations

- Do not commit the local profile or database.
- Remove private details before sharing exports.
- Store API keys in environment variables if optional providers are added later.
- Review every generated document before submitting it.

## Snapshots y respaldos de Fase 3

`discover --save` y `vacancies evaluate` guardan el perfil utilizado junto con la
vacante, evidencia y evaluación. Los hashes permiten reproducibilidad; no anonimizan
esos snapshots. Cambiar `profile.json` no borra versiones anteriores de SQLite.
Los backups incluyen el historial completo y deben protegerse como la base original.
Mantenerlos fuera del checkout; revisar exportaciones antes de compartirlas.
Sin `--save`, `discover` conserva su funcionamiento sin acceso al perfil o SQLite.

## Documentos y aprobaciones — Fase 4

El almacén `resumes/` contiene identidad/contacto, evidencia, maestros, documentos
y manifiestos; el tracker guarda borradores y snapshots aprobados. No existe
telemetría o sender. Los errores y listados por defecto no imprimen el CV completo;
`show`, `review` y exportación sí muestran/escriben datos privados a petición expresa.
No compartir esas salidas como logs públicos.

Los documentos y SQLite no están cifrados. Proteger también los backups, revisar
ACL en Windows y conservar `resumes/` junto a SQLite al recuperar. La restauración
oficial revoca autorizaciones activas; no copiar una base antigua para reactivarlas.
No usar una carpeta dentro del checkout como almacén privado. Las evidencias se
verifican por hash y atestación humana; su verdad no se certifica automáticamente.
Detalles en [CV y candidaturas](RESUMES_CANDIDACIES.md).
