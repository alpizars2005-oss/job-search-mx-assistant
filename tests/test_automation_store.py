import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.models import CandidateProfile
from test_persistence import normalized_job


class AutomationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = ApplicationDatabase(Path(self.temporary.name) / 'test.sqlite3')
        self.profile = CandidateProfile(skills=['python'], target_roles=['developer'])

    def store(self):
        try:
            from jobsearch_assistant.automation_store import AutomationStore
        except ImportError:
            self.fail('Transactional automation store is not implemented')
        return AutomationStore(self.database)

    def test_repeated_observation_reuses_evaluation_even_when_retrieved_at_changes(self):
        store = self.store()
        first_run = store.start('config', 'profile')
        first = store.observe(first_run, normalized_job(), self.profile)
        store.finish(first_run, 'success', [])
        second_run = store.start('config', 'profile')
        second = store.observe(second_run, normalized_job(retrieved_at='2026-11-06T00:00:00Z'), self.profile)
        self.assertEqual(first['change'], 'new')
        self.assertEqual(second['change'], 'unchanged')
        self.assertEqual(first['evaluation_id'], second['evaluation_id'])
        self.assertEqual(len(self.database.list_evaluations(first['vacancy_id'])), 1)
        self.assertEqual(len(self.database.list_vacancies()), 1)
        self.assertEqual(self.database.list(), [])

    def test_changed_job_and_profile_preserve_distinct_historical_snapshots(self):
        store = self.store()
        run = store.start('config', 'profile')
        first = store.observe(run, normalized_job(), self.profile)
        store.finish(run, 'success', [])
        run = store.start('config', 'profile')
        changed = store.observe(run, normalized_job(description='Different synthetic Python role'), self.profile)
        self.assertEqual(changed['change'], 'changed')
        store.finish(run, 'success', [])
        run = store.start('config', 'new-profile')
        updated_profile = replace(self.profile, skills=['linux'])
        reevaluated = store.observe(run, normalized_job(description='Different synthetic Python role'), updated_profile)
        self.assertEqual(reevaluated['change'], 'reevaluated')
        history = self.database.list_evaluations(first['vacancy_id'])
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]['job_snapshot']['description'], 'Synthetic Python role')
        self.assertEqual(history[0]['profile_snapshot']['skills'], ['python'])
        self.assertEqual(history[2]['profile_snapshot']['skills'], ['linux'])

    def test_failure_between_vacancy_and_evaluation_rolls_back_whole_observation(self):
        store = self.store()
        run = store.start('config', 'profile')
        with patch.object(self.database, '_save_evaluation_on_connection', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):
                store.observe(run, normalized_job(), self.profile)
        self.assertEqual(self.database.list_vacancies(), [])
        with self.database._connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM automation_items').fetchone()[0], 0)

    def test_restart_marks_abandoned_run_and_keeps_committed_results(self):
        store = self.store()
        run = store.start('config', 'profile')
        saved = store.observe(run, normalized_job(), self.profile)
        restarted = self.store()
        next_run = restarted.start('config', 'profile')
        self.assertNotEqual(run, next_run)
        self.assertEqual(restarted.show(run)['status'], 'interrupted')
        self.assertEqual(restarted.show(next_run)['recovered_runs'], 1)
        self.assertEqual(len(self.database.list_evaluations(saved['vacancy_id'])), 1)
        self.assertEqual(restarted.observe(next_run, normalized_job(), self.profile)['change'], 'unchanged')

    def test_resume_candidacy_tables_are_not_automatically_populated(self):
        store = self.store()
        run = store.start('config', 'profile')
        store.observe(run, normalized_job(), self.profile)
        store.finish(run, 'success', [])
        with self.database._connection() as connection:
            for table in ('applications', 'candidacies', 'candidacy_authorizations'):
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)

    def test_summary_and_history_never_contain_private_profile_or_remote_text(self):
        store = self.store()
        run = store.start('config', 'profile')
        profile = replace(self.profile, headline='PRIVATE PERSON CONTACT secret@example.test')
        store.observe(run, normalized_job(title='PRIVATE JOB TITLE', description='PRIVATE DESCRIPTION'), profile)
        result = store.finish(run, 'success', [])
        visible = json.dumps([result, store.history(), store.show(run)], ensure_ascii=False)
        for secret in ('PRIVATE', 'secret@example.test', 'Synthetic Co', 'description', 'headline'):
            self.assertNotIn(secret, visible)
        self.assertEqual(result['counts']['new'], 1)

    def test_http_state_survives_new_store_without_raw_urls(self):
        store = self.store()
        state = {'version': 1, 'providers': {'lever': {'failures': 2, 'paused_until': None,
                                                    'not_before': '2026-12-01T00:00:00+00:00'}}}
        store.save_http_state(state)
        self.assertEqual(self.store().load_http_state(), state)

    def test_duplicate_callback_in_same_run_has_one_item(self):
        store = self.store()
        run = store.start('config', 'profile')
        first = store.observe(run, normalized_job(), self.profile)
        second = store.observe(run, normalized_job(), self.profile)
        self.assertEqual(first, second)
        self.assertEqual(store.finish(run, 'success', [])['counts']['total'], 1)


if __name__ == '__main__':
    unittest.main()
