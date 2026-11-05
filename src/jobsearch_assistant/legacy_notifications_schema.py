"""Historical schema only. No producer, configuration or delivery transport exists."""
import sqlite3


def create_notification_tables(connection: sqlite3.Connection) -> None:
    """Create additive schema inside the caller's migration transaction."""
    connection.execute('''
        CREATE TABLE IF NOT EXISTS notification_outbox (
            id INTEGER PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK(kind IN (
                'priority','review_pending','eligibility_pending',
                'source_error','recovered','run_summary')),
            entity_id INTEGER CHECK(entity_id IS NULL OR entity_id > 0),
            event_count INTEGER NOT NULL CHECK(event_count >= 0),
            language TEXT NOT NULL CHECK(language IN ('es','en')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','sending','sent','failed','uncertain')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
            not_before REAL NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE INDEX IF NOT EXISTS notification_outbox_pending
        ON notification_outbox(status, id)
    ''')
    # One configured chat per database. A shared cooldown is conservative even
    # if an operator changes that chat or rotates the bot token.
    connection.execute('''
        CREATE TABLE IF NOT EXISTS notification_delivery_state (
            id INTEGER PRIMARY KEY CHECK(id=1),
            next_allowed_at REAL NOT NULL DEFAULT 0
        )
    ''')



def retire_notification_tables(connection):
    """Preserve history and block old runtimes from creating delivery intents."""
    for table in ('notification_outbox', 'notification_delivery_state',
                  'automation_notification_health'):
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists:
            continue
        for action in ('INSERT', 'UPDATE', 'DELETE'):
            connection.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_retired_{action.lower()}
                BEFORE {action} ON {table}
                BEGIN SELECT RAISE(ABORT, 'Retired notification history'); END""")
    for action in ('INSERT', 'UPDATE OF notifications_json'):
        name = 'insert' if action == 'INSERT' else 'update'
        condition = ('NEW.notifications_json IS NOT NULL' if action == 'INSERT' else
                     'NEW.notifications_json IS NOT OLD.notifications_json')
        connection.execute(f"""CREATE TRIGGER IF NOT EXISTS automation_runs_retired_{name}
            BEFORE {action} ON automation_runs WHEN {condition}
            BEGIN SELECT RAISE(ABORT, 'Retired notification history'); END""")
