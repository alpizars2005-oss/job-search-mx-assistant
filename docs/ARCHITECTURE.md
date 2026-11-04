# Architecture

The project uses a small layered architecture:

- `models.py`: portable domain objects.
- `evaluator.py`: deterministic and explainable fit scoring.
- `database.py`: SQLite persistence and schema management.
- `config.py`: cross-platform data paths and profile/settings files.
- `exporters.py`: CSV and JSON interchange.
- `search_queries.py`: safe, user-initiated search-query generation.
- `cli.py`: automation-friendly interface.
- `gui.py`: Tkinter desktop interface.

The GUI and CLI do not duplicate business logic. Both call the evaluator and database layers directly.

## Design constraints

- Python standard library for the default installation.
- User data outside the repository.
- No mandatory API key.
- No authenticated scraping.
- No automatic application submission.
- Explainable scoring with visible evidence.


## Descubrimiento público implementado en Fase 2

El paquete `sources` permanece separado de los modelos y la base del tracker:

- `models.py`: configuración validada, límites, vacante normalizada y reportes.
- `http.py`: transporte GET urllib sin redirects y cliente con cuotas compartidas,
  timeouts, límite de bytes, reintentos/jitter, Retry-After y pausas en memoria.
- `adapters.py`: endpoints fijos, validación y transformación de cada contrato ATS.
- `discovery.py`: orquestación serial y deduplicación por proveedor/tablero/ID.
- `config.py`: configuración JSON explícita, acotada y separada de perfiles.

`jobsearch discover` usa ese paquete sin abrir SQLite o leer perfiles. La GUI,
evaluador y exportadores históricos conservan sus interfaces. La salida incluye
procedencia por campo y evidencia regional sin interpretación; no conecta el
score anterior a un filtro de elegibilidad. Transporte y reloj son inyectables
para pruebas offline. Ver [contrato y operación](JOB_SOURCES.md).
