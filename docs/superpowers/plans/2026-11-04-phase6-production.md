# Plan B — operación privada y reportes diarios

Base explícita: PR #11, rama codex/phase-6-hardening. No fusionar automáticamente.
Spec: ../specs/2026-11-04-phase6-production-design.md. Misión completa del usuario
rige sobre pausas de aprobación del flujo de skills: preparación autorizada autónoma.

## Tareas y propiedad

1. Root: backup/verify/restore de conjunto privado, inventario/retención simulada,
   coordinación de escrituras CLI mediante RunLock, pruebas RED→GREEN de integridad,
   concurrencia, fallo parcial/disco, recuperación/autorizaciones y no borrado.
2. Agente reports: daily_reports.py/daily_report_cli.py y pruebas sintéticas.
   Registro por archivos inmutables, sin schema nuevo, salida agregada segura,
   zona local, 14:00 configurable, catchup acotado, misma exclusión que automation.
3. Agente deployment: release offline fijada, instalación/actualización/rollback
   conservadores, systemd oneshot+timers y pruebas aisladas sin modificar host.
4. Root integra CLI, dependencia tzdata solo Windows si necesaria para IANA,
   documentación producción/Work/backup/retención, medidas sintéticas de recursos.
5. Revisión independiente read-only del SHA, corregir hallazgos confirmados,
   unittest+pytest+pip+compile, instalación limpia offline y calendario/sintaxis real.
6. PR apilado contra codex/phase-6-hardening, dependencia #11 explícita, attach,
   CI ocho jobs del encabezado real. Sin merge o pilotaje de PizzaLab.

## Criterios de aceptación

- Sin fuentes funciona offline; con respuestas sintéticas conserva todo el flujo.
- Backups coherentes verificados, destino nuevo, recuperación revoca permisos y
  conserva/revisa restricciones; configuración y evidencias incluidas.
- Un reporte por fecha debida, ventanas explícitas sin perder horas, recuperable,
  JSON+Markdown válidos; simulación/manual-applied jamás equivale a envío real.
- Inventario y retención no eliminan ni modifican documentos reales.
- Instalador fija SHA, no instala/activa nada en PizzaLab desde Cloud.
- Evidencia local, CI, límites Debian/LXC/systemd/ACL y Work diferenciados.
