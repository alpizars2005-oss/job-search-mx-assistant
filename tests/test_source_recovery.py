import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.automation_cli import recover_sources, source_state
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.sources.models import SourceError
from jobsearch_assistant.workflow_contracts import WorkflowError, canonical_json


class SourceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = ApplicationDatabase(Path(self.temp.name) / 'applications.sqlite3')
        self.now = datetime(2026, 11, 4, 20, tzinfo=timezone.utc)
        # Compatibility with an in-progress parent migration; fresh schema 5
        # creates this same additive operational audit table.
        with self.database._connection() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS operational_control_events (
                id INTEGER PRIMARY KEY,kind TEXT NOT NULL,provider TEXT,
                reason_code TEXT NOT NULL,state_digest TEXT NOT NULL,created_at TEXT NOT NULL)''')

    def suspend(self, seconds=-1, *, unbounded=False, quarantine=False):
        deadline = None if unbounded else (self.now + timedelta(seconds=seconds)).isoformat()
        state = {'failures': 1, 'paused_until': None, 'not_before': deadline,
                 'suspension': {'reason': 'retry_after_horizon', 'kind': 'seconds',
                                'value': '9' * 5000 if unbounded else '90000',
                                'observed_at': (self.now + timedelta(seconds=seconds - 90000)).isoformat(),
                                'not_before': deadline}}
        with self.database._connection() as connection:
            connection.execute('INSERT OR REPLACE INTO automation_http_state VALUES (?,?)',
                               ('greenhouse', canonical_json(state)))
            if quarantine:
                connection.execute("INSERT OR REPLACE INTO meta VALUES ('source_review_required','1')")
        return source_state(self.database)

    def recover(self, **options):
        state = source_state(self.database)
        return recover_sources(self.database, expected_digest=state['state_digest'],
                               reason_code='external_deadline_elapsed', provider='greenhouse',
                               now=self.now, **options)

    def test_expired_manual_suspension_can_be_resumed_once_with_atomic_audit(self):
        original = self.suspend()
        result = self.recover()
        self.assertIsNone(result['http_state']['providers']['greenhouse']['suspension'])
        self.assertNotEqual(result['state_digest'], original['state_digest'])
        with self.database._connection() as connection:
            events = [dict(row) for row in connection.execute('SELECT * FROM operational_control_events')]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'source_resume')
        self.assertEqual(events[0]['provider'], 'greenhouse')
        self.assertEqual(events[0]['state_digest'], original['state_digest'])
        with self.assertRaises(SourceError):
            self.recover()

    def test_future_and_unbounded_restrictions_are_never_shortened(self):
        for options, code in [({'seconds': 90000}, 'retry_after_active'),
                              ({'unbounded': True}, 'retry_after_unbounded')]:
            with self.subTest(options=options):
                original = self.suspend(**options)
                with self.assertRaises(SourceError) as error:
                    self.recover()
                self.assertEqual(error.exception.code, code)
                self.assertEqual(source_state(self.database), original)

    def test_changed_digest_reason_or_policy_cannot_authorize_resume(self):
        original = self.suspend()
        for changes in ({'expected_digest': '0' * 64}, {'reason_code': 'private arbitrary text'}):
            parameters = {'expected_digest': original['state_digest'],
                          'reason_code': 'external_deadline_elapsed',
                          'provider': 'greenhouse', 'now': self.now}
            parameters.update(changes)
            with self.subTest(changes=changes), self.assertRaises(WorkflowError):
                recover_sources(self.database, **parameters)
        with patch.dict(os.environ, {'AUTO_SUBMIT': 'true'}), self.assertRaises(WorkflowError):
            self.recover()
        self.assertEqual(source_state(self.database), original)

    def test_restored_quarantine_requires_review_without_erasing_http_history(self):
        original = self.suspend(quarantine=True)
        self.assertTrue(original['review_required'])
        result = recover_sources(self.database, expected_digest=original['state_digest'],
                                 reason_code='external_limits_reviewed', review_restore=True, now=self.now)
        self.assertFalse(result['review_required'])
        self.assertEqual(result['http_state'], original['http_state'])
        with self.database._connection() as connection:
            event = connection.execute('SELECT * FROM operational_control_events').fetchone()
        self.assertEqual(event['kind'], 'restored_sources_review')
        self.assertIsNone(event['provider'])

    def test_quarantine_review_cannot_bypass_known_future_or_unbounded_cooldown(self):
        for options in ({'seconds': 90000}, {'unbounded': True}):
            with self.subTest(options=options):
                original = self.suspend(quarantine=True, **options)
                with self.assertRaises(SourceError):
                    recover_sources(self.database, expected_digest=original['state_digest'],
                                    reason_code='external_limits_reviewed', review_restore=True, now=self.now)
                self.assertEqual(source_state(self.database), original)

    def test_diagnostics_do_not_contact_sources_or_leak_home(self):
        self.suspend()
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network')):
            state = source_state(self.database)
        self.assertEqual(len(state['state_digest']), 64)
        self.assertNotIn(self.temp.name, json.dumps(state))

    def test_two_operators_cannot_consume_one_snapshot_twice(self):
        original = self.suspend()
        def attempt():
            try:
                recover_sources(self.database, expected_digest=original['state_digest'],
                                reason_code='external_deadline_elapsed', provider='greenhouse', now=self.now)
                return 'resumed'
            except WorkflowError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: attempt(), range(2)))
        self.assertCountEqual(results, ['resumed', 'source_state_changed'])
        with self.database._connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM operational_control_events').fetchone()[0], 1)

    def test_audit_failure_rolls_back_state_change(self):
        original = self.suspend()
        with self.database._connection() as connection:
            connection.execute("CREATE TRIGGER synthetic_audit_failure BEFORE INSERT ON operational_control_events BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.recover()
        self.assertEqual(source_state(self.database), original)


if __name__ == '__main__':
    unittest.main()
