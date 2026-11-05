"""Additive local orchestration schema; called inside the migration transaction."""


def create_automation_tables(connection):
    connection.execute('''CREATE TABLE automation_runs (
        id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
        status TEXT NOT NULL CHECK(status IN
          ('running','success','partial','deadline','interrupted','failed')),
        config_digest TEXT NOT NULL, profile_digest TEXT NOT NULL,
        recovered_runs INTEGER NOT NULL DEFAULT 0,
        reports_json TEXT NOT NULL DEFAULT '[]'
    )''')
    connection.execute('''CREATE TABLE automation_observations (
        vacancy_id INTEGER PRIMARY KEY REFERENCES vacancies(id),
        semantic_digest TEXT NOT NULL, profile_digest TEXT NOT NULL,
        algorithm_version TEXT NOT NULL,
        evaluation_id INTEGER NOT NULL REFERENCES evaluations(id)
    )''')
    connection.execute('''CREATE TABLE automation_items (
        run_id TEXT NOT NULL REFERENCES automation_runs(id),
        vacancy_id INTEGER NOT NULL REFERENCES vacancies(id),
        evaluation_id INTEGER NOT NULL REFERENCES evaluations(id),
        change_kind TEXT NOT NULL CHECK(change_kind IN ('new','changed','reevaluated','unchanged')),
        classification TEXT NOT NULL,
        PRIMARY KEY(run_id,vacancy_id)
    )''')
    connection.execute('''CREATE TABLE automation_http_state (
        provider TEXT PRIMARY KEY, state_json TEXT NOT NULL
    )''')
    connection.execute('''CREATE TABLE automation_source_health (
        provider TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
        episode TEXT, last_success TEXT, last_failure TEXT,
        last_status TEXT NOT NULL
    )''')
    connection.execute('''CREATE INDEX automation_runs_started ON automation_runs(started_at)''')

