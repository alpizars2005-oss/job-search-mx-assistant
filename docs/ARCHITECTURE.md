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
