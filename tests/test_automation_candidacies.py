import sqlite3
from contextlib import closing
from dataclasses import replace

from jobsearch_assistant.automation_store import AutomationStore
from jobsearch_assistant.config import default_profile
from jobsearch_assistant.migrations import backup_database, restore_backup
from jobsearch_assistant.workflow_contracts import WorkflowError
from test_candidacies import WorkflowCase


class AutomationCandidacyTests(WorkflowCase):
    def test_refresh_retains_approval_then_material_change_revokes_without_submitting(self):
        candidate = self.create()
        authorization = self.authorize(candidate)
        store = AutomationStore(self.database)
        run = store.start('config', 'profile')
        store.observe(run, replace(self.job, retrieved_at='2026-11-06T00:00:00Z'), default_profile())
        store.finish(run, 'success', [])
        with self.database._connection() as connection:
            self.assertEqual(connection.execute('SELECT status FROM candidacy_authorizations WHERE authorization_id=?',
                                                (authorization,)).fetchone()[0], 'active')
        run = store.start('config', 'profile')
        store.observe(run, replace(self.job, title='Different job'), default_profile())
        store.finish(run, 'success', [])
        with self.assertRaises(WorkflowError):
            self.workflow.simulate(authorization)
        self.assertEqual(self.workflow.get(candidate)['status'], 'saved')
        self.assertEqual(len(self.database.list()), 1)
        self.assertEqual(len(self.workflow.list()), 1)

    def test_schema_four_restore_preserves_history_and_revokes_remote_intents(self):
        candidate = self.create()
        authorization = self.authorize(candidate)
        store = AutomationStore(self.database)
        run = store.start('config', 'profile')
        store.observe(run, self.job, default_profile())
        store.finish(run, 'success', [])
        backup = self.root / 'backup.sqlite3'
        restored = self.root / 'restored.sqlite3'
        backup_database(self.database.path, backup)
        restore_backup(backup, restored)
        with closing(sqlite3.connect(restored)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '4')
            self.assertEqual(connection.execute('SELECT status FROM candidacy_authorizations WHERE authorization_id=?',
                                                (authorization,)).fetchone()[0], 'invalidated')
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM notification_outbox WHERE status='pending'").fetchone()[0], 0)
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM notification_outbox WHERE status='uncertain'").fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM automation_items').fetchone()[0], 1)
