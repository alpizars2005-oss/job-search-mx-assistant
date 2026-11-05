# Revisión de Claude preparada, sin ejecución real

Fase 5 prepara una integración oficial de Claude Code mediante GitHub Actions.
**Permanece desactivada por defecto y no se ejecutó ninguna revisión de Claude.**
Cloud no tiene secretos ni identidades salientes configurados para Claude. No se
instaló Claude, contrató servicio, creó credencial ni consumió API de modelos.
Las pruebas usan respuestas de GitHub y registros SDK enteramente sintéticos.

## Fuentes e inputs comprobados

Documentación consultada el 2026-11-05: [GitHub Actions de Claude Code](https://code.claude.com/docs/en/github-actions),
[CLI](https://code.claude.com/docs/en/cli-reference),
[configuración](https://github.com/anthropics/claude-code-action/blob/c0949c50a78c1ec8ce2647db36629b870e715d0c/docs/configuration.md)
y [seguridad oficial](https://github.com/anthropics/claude-code-action/blob/c0949c50a78c1ec8ce2647db36629b870e715d0c/docs/security.md).
La acción está fijada al commit oficial
`c0949c50a78c1ec8ce2647db36629b870e715d0c`, publicado el 2026-11-04,
que fija Claude Code 2.1.318 y Agent SDK 0.3.318. También se fijan checkout y
upload-artifact por SHA. Esto no certifica la cadena de distribución del proveedor.

Se verificaron [action.yml](https://github.com/anthropics/claude-code-action/blob/c0949c50a78c1ec8ce2647db36629b870e715d0c/action.yml),
[detección de modo](https://github.com/anthropics/claude-code-action/blob/c0949c50a78c1ec8ce2647db36629b870e715d0c/src/modes/detector.ts),
[preparación del agente](https://github.com/anthropics/claude-code-action/blob/c0949c50a78c1ec8ce2647db36629b870e715d0c/src/modes/agent/index.ts),
[servidores MCP](https://github.com/anthropics/claude-code-action/blob/c0949c50a78c1ec8ce2647db36629b870e715d0c/src/mcp/install-mcp-server.ts)
y [conversión de argumentos a SDK](https://github.com/anthropics/claude-code-action/blob/c0949c50a78c1ec8ce2647db36629b870e715d0c/base-action/src/parse-sdk-options.ts).
`prompt` explícito selecciona modo agente; no se usa el input obsoleto `mode`.
`github_token` explícito usa el token efímero de lectura del job y evita el
intercambio por un token de la App con permisos de escritura. No requiere instalar
la App para este camino. No se solicita OIDC, PAT ni permisos de escritura.

La CLI documenta `--disallowedTools '*'` para retirar todas las herramientas,
incluidas MCP. `--bare`, `--restricted`, MCP vacío y `--strict-mcp-config` reducen
la carga de personalizaciones. `allowedTools` vacío solo quitaría aprobaciones
automáticas y no constituye aislamiento. Se evita `--tools ''`: el parser de esta
versión de la acción no conserva correctamente valores vacíos. No hay plugins,
hooks confiados al PR ni herramientas Bash, Read, Write, Edit, red, GitHub o commits
disponibles para el modelo. El proveedor instala y configura su propio runtime;
la acción puede modificar su configuración Git local sin publicar cambios.

## Activación futura, pendiente de autorización

El YAML no crea la protección de un environment. Un administrador deberá realizar
la configuración y autorizar expresamente el coste antes de usarlo:

1. Integrar y revisar el workflow, script y prompt en `main`; proteger `main`.
2. Crear el environment `claude-review` con revisores humanos obligatorios,
   prevención de autoaprobación y despliegues limitados a ramas protegidas. No
   permitir bypass administrativo de las aprobaciones. El preparador verifica las
   reglas que expone la API; el administrador sigue siendo parte de la confianza.
3. Configurar una credencial autorizada como secreto **del environment**
   `ANTHROPIC_API_KEY`, nunca en el repositorio ni en mensajes. Restringir uso y
   presupuesto con el proveedor. El workflow limita la sesión a un turno,
   presupuesto de 1 USD y diez minutos; los límites de la CLI no sustituyen un
   límite de facturación de la cuenta.
4. Solo tras autorizar el servicio, definir la variable del repositorio
   `CLAUDE_REVIEW_ENABLED=true`. Ausente o con otro valor, el job se omite.
5. Despachar manualmente desde `main`, indicando PR y SHA completo exacto de su
   HEAD. Revisar el diff antes de aprobar el environment: no incluir secretos,
   perfiles, CV, bases privadas ni datos personales. La aprobación autoriza ese
   procesamiento externo concreto. Mantener desactivados los logs de depuración.

El preflight rechaza contexts distintos de `workflow_dispatch` en `main`, hosts
distintos de github.com/api.github.com, actores sin escritura o bots, environment
sin revisores/prevent_self_review, main no protegido, PR cerrado o con otra base,
forks y repos distintos. Comprueba HEAD y base antes/después de obtener el diff;
la base debe coincidir con el SHA confiable que ejecuta el workflow. Si `main`
avanzó desde el despacho, hace falta un despacho nuevo. Una API inaccesible, un
403, una respuesta inesperada o reglas no disponibles detienen la preparación;
no se amplían permisos ni se intenta otro token.

## Diagnósticos de Actions y límites de los logs

Hardening L-02 consultado el 2026-11-05 contra la documentación oficial de
[logs de depuración](https://docs.github.com/en/actions/how-tos/monitor-workflows/enable-debug-logging)
y [disponibilidad de contextos](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts).
GitHub admite `ACTIONS_STEP_DEBUG` y `ACTIONS_RUNNER_DEBUG` tanto como secretos
como variables, y permite activar diagnóstico al reejecutar un workflow. La
precedencia oficial de secretos sobre variables no se utiliza para ocultar una
señal: se comprueban por separado y cualquier valor `true` o `1` bloquea el flujo.

Un primer paso, antes de checkout, rechaza esas cuatro entradas, las variables
de entorno de Actions y `RUNNER_DEBUG`, además de `runner.debug`. El contexto del
runner se consulta en pasos, donde GitHub lo admite. El preparador repite el
control antes de acceder a la API, obtener el diff o publicar outputs; no basta
con asignar `ACTIONS_STEP_DEBUG=false` en el job para apagar diagnósticos del runner.
Un bloqueo termina con un código fijo y sin archivos, diff ni credenciales de
revisión. Los artefactos siguen limitados a manifiesto e informe durante siete días.

Estas defensas reducen exposición accidental; no demuestran redacción completa
ni control sobre los logs internos de GitHub o del proveedor. La acción oficial
continúa imprimiendo el prompt incluso sin diagnóstico. Es obligatorio revisar
humanamente que el diff sea publicable antes de autorizar una futura ejecución,
mantener los diagnósticos desactivados y no reejecutar con debug una revisión que
contenga información reservada. No se ha invocado Claude para verificar este cambio.

## Aislamiento, datos y evidencia

Solo se extraen del commit confiable dos archivos: el preparador y el prompt.
Se mueven a una carpeta temporal confiable; el directorio de ejecución del modelo
conserva únicamente Git, sin árbol del PR ni configuración ejecutable. El diff
jamás se extrae como archivos o se ejecuta. El modelo recibe texto JSON marcado
como no confiable y las instrucciones confiables se añaden por archivo separado.
No se incluyen título, cuerpo, comentarios o nombre de rama del PR en el prompt.

El preparador usa únicamente GET a rutas construidas para API GitHub pública:
permisos del actor, environment, rama main, PR y comparación de SHA inmutables.
No utiliza URLs devueltas por la API. Rechaza redirects y limita cada lectura;
timeout de diez segundos por operación, sin reintentos. Acepta como máximo 64
archivos y 96.000 bytes de diff UTF-8; rechaza binarios, vacío y discrepancias en
el número de archivos. Los permisos del job son `contents: read`,
`pull-requests: read` y `actions: read`; este último es necesario para [leer la
protección del environment](https://docs.github.com/en/rest/deployments/environments#get-an-environment).
No ejecuta pruebas del PR ni instala sus dependencias. Estos límites pueden
rechazar cambios legítimos; no se trunca una revisión y se presenta como completa.

El manifiesto identifica repositorio, PR, base/head, SHA-256 y tamaño del diff,
cobertura y `tests=not_executed`. `prepared_not_reviewed` y
`claude_invoked=false` nunca representan un dictamen. Tras una futura ejecución
autorizada, se revalida la selección y se extrae solo el resultado final del SDK,
rechazando sesiones sin éxito, con herramientas anunciadas, MCP o llamadas a
herramientas. El informe conserva el manifiesto y el hash del registro SDK; su
texto continúa siendo no confiable y requiere revisión humana. No se suben el
diff, la conversación completa ni el directorio temporal como artefactos.

La salida final solicitada incluye severidad, evidencia, líneas, confianza y
validación sugerida por hallazgo. El contenedor del informe fija pruebas no
ejecutadas aunque el modelo alegue haberlas corrido. `show_full_output=false` y
`display_report=false` evitan publicar conversación completa o renderizar Markdown
del modelo como resumen. **La versión oficial sí imprime el prompt de entrada en
sus logs de preparación**, incluso con `show_full_output=false`: revisar el diff
como contenido publicable antes de autorizar. Los logs de Actions y el envío al
proveedor constituyen exposición externa; no hay garantía de redacción de
secretos arbitrarios que se hayan incluido por error en el código.

Solo se conservan manifiesto e informe JSON como artefactos durante siete días;
no se crean comentarios, revisiones GitHub, ramas, commits, merges o despliegues.
Cambiar HEAD/base invalida su aplicación al PR actual; incluso sin hallazgos, el
informe no certifica seguridad ni habilita auto-merge. La prevención de prompt
injection combina retirada de herramientas y límites de credenciales, no solo
instrucciones. No se ha validado contra el runtime real del proveedor.

## Validación reproducible

```bash
.venv/bin/python -m unittest discover -s tests -p test_claude_review.py -v
```

Pruebas offline ejercitan las APIs del preparador y el lector HTTP con transporte
inyectado: PR/SHA/base exactos, cambios durante descarga, forks, permisos y
protección, contenido adversarial, límites, redirects, media, errores redactados,
publicación exclusiva y extracción de registros SDK sintéticos. Esto verifica
preparación y validación local; no demuestra conectividad con Claude, uso real de
credenciales, aprobación del environment o una revisión independiente de Claude.
También cubren todas las señales de diagnóstico anteriores, conflicto entre
variable activa y secreto desactivado, ausencia de lecturas API/outputs cuando se
bloquea y funcionamiento normal con diagnóstico desactivado.
