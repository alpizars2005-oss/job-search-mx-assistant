# Guía de usuario

1. Ejecuta `jobsearch init --language es`.
2. Abre `jobsearch-gui`.
3. Completa la pestaña Perfil.
4. Pega la descripción de una vacante en Analizar.
5. Revisa la puntuación, coincidencias, faltantes y riesgos.
6. Guarda las vacantes prometedoras.
7. Actualiza el estado y las notas desde la pestaña Postulaciones o mediante la terminal.
8. Exporta copias CSV o JSON regularmente.

La evaluación nueva `matching_v2` comprueba exclusiones antes del puntaje y distingue
negaciones reconocidas como `not remote`. Un dato esencial desconocido produce
`insufficient_information`; la puntuación de habilidades no confirma elegibilidad.
Las reglas son acotadas: revisa la modalidad, contratación desde México y requisitos
obligatorios en la publicación original. Los históricos conservan su resultado y
algoritmo anterior. Consulta [operación y límites](SQLITE_MATCHING.md).

## Importar un perfil

```bash
jobsearch profile import profile.json
```

El archivo debe contener un objeto JSON. `name`, `headline` y `location` deben ser textos. Las habilidades, idiomas, roles, ubicaciones, niveles de experiencia y restricciones deben ser listas de textos. `remote_only` acepta `true` o `false`, sin comillas; `skill_aliases` es un objeto que relaciona cada habilidad con una lista de alias.

Los campos omitidos conservan sus valores predeterminados y los campos desconocidos se ignoran. Un tipo incorrecto produce un error de importación sin reemplazar el perfil anterior. El mensaje identifica el campo, no repite su contenido personal.

## Si un archivo guardado no carga

Al cargar un perfil inválido, la aplicación usa el perfil predeterminado en memoria. Un archivo de ajustes inválido usa español. Los archivos originales no se reescriben durante esa carga: esto evita un cierre inesperado, pero no repara el contenido ni confirma que tus preferencias se hayan recuperado.

Antes de editar o volver a guardar el perfil, conserva una copia del archivo original. Revisa `profile.json` y `settings.json` dentro del directorio de datos indicado en [Privacidad](PRIVACY.md).
