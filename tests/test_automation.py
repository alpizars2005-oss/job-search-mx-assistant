import json
import tempfile
import unittest
from pathlib import Path

from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.models import CandidateProfile
from jobsearch_assistant.sources.http import SafeHttpClient
from jobsearch_assistant.sources.models import HttpResponse, RequestPolicy, SourceConfig
from urllib.error import URLError


def body(identifier=10):
    return {'jobs': [{'id': identifier, 'title': 'Junior Python developer',
                      'location': {'name': 'Remote'}, 'content': '<p>Synthetic Python work</p>',
                      'absolute_url': f'https://boards.greenhouse.io/synthetic/jobs/{identifier}'}]}


def response(payload):
    return HttpResponse(200, {'Content-Type': 'application/json'}, json.dumps(payload).encode())


class AutomationTests(unittest.TestCase):
    def setUp(self):
        try:
            from jobsearch_assistant.automation import AutomationRunner
            self.runner_type = AutomationRunner
        except ImportError:
            self.fail('One-shot orchestration is not implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = ApplicationDatabase(Path(self.temp.name) / 'test.sqlite3')
        self.profile = CandidateProfile(skills=['python'])
        self.policy = RequestPolicy(max_retries=0, min_interval=0, max_wait=0)

    def runner(self, configs, transport, **options):
        try:
            from jobsearch_assistant.runtime_control import RunControl
        except ImportError:
            self.fail('One-shot orchestration is not implemented')
        control = options.pop('control', RunControl(30))
        client = SafeHttpClient(self.policy, transport=transport, control=control)
        return self.runner_type(self.database, self.profile, configs, self.policy,
                                control=control, client=client, **options)

    def test_enabled_sources_only_and_same_search_is_idempotent(self):
        calls = []
        def transport(url, timeout, max_bytes):
            calls.append(url)
            return response(body())
        configs = [SourceConfig('greenhouse', 'synthetic', 'Synthetic', True),
                   SourceConfig('lever', 'disabled', 'Disabled', False)]
        first = self.runner(configs, transport).run()
        second = self.runner(configs, transport).run()
        self.assertEqual(len(calls), 2)
        self.assertEqual(first['status'], 'success')
        self.assertEqual(first['counts']['new'], 1)
        self.assertEqual(second['counts']['unchanged'], 1)
        self.assertEqual(len(self.database.list_vacancies()), 1)
        self.assertEqual(len(self.database.list_evaluations(1)), 1)
        self.assertEqual(self.database.list(), [])

    def test_partial_provider_failure_preserves_other_valid_jobs(self):
        def transport(url, timeout, max_bytes):
            return response(body()) if 'greenhouse' in url else HttpResponse(503, {}, b'')
        configs = [SourceConfig('greenhouse', 'synthetic', 'Synthetic', True),
                   SourceConfig('ashby', 'synthetic', 'Synthetic', True)]
        result = self.runner(configs, transport).run()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['counts']['new'], 1)
        self.assertEqual([r['status'] for r in result['sources']], ['ok', 'error'])
        self.assertEqual(len(self.database.list_vacancies()), 1)

    def test_retry_after_cooldown_survives_new_client_and_process_state(self):
        calls = []
        def transport(url, timeout, max_bytes):
            calls.append(url)
            return HttpResponse(429, {'Retry-After': '3600'}, b'')
        config = [SourceConfig('greenhouse', 'synthetic', 'Synthetic', True)]
        first = self.runner(config, transport).run()
        second = self.runner(config, transport).run()
        self.assertEqual(len(calls), 1)
        self.assertEqual(first['status'], 'partial')
        self.assertEqual(second['sources'][0]['status'], 'paused')

    def test_structured_logs_have_no_job_or_profile_text(self):
        logs = []
        config = [SourceConfig('greenhouse', 'synthetic', 'PRIVATE COMPANY', True)]
        result = self.runner(config, lambda *args: response(body()), log=logs.append).run()
        text = json.dumps([logs, result])
        for private in ('PRIVATE', 'Junior Python', 'Synthetic Python', 'http', 'headline'):
            self.assertNotIn(private, text)
        self.assertEqual(logs[0]['event'], 'run_started')
        self.assertEqual(logs[-1]['event'], 'run_finished')

    def test_run_with_disabled_sources_does_not_touch_network(self):
        result = self.runner([SourceConfig('lever', 'synthetic', 'Synthetic')],
                             lambda *args: self.fail('Disabled source used network')).run()
        self.assertEqual(result['counts']['total'], 0)
        self.assertEqual(result['status'], 'success')

    def test_first_lever_page_is_committed_before_next_page_fails(self):
        self.policy = RequestPolicy(max_retries=0, min_interval=0, page_size=1, max_pages=2)
        calls = []
        def transport(url, timeout, max_bytes):
            calls.append(url)
            if len(calls) == 2:
                self.assertEqual(len(self.database.list_vacancies()), 1)
                raise URLError('Synthetic timeout with PRIVATE text')
            return response([{'id': 'one', 'text': 'Junior Python', 'categories': {},
                              'hostedUrl': 'https://jobs.lever.co/synthetic/one',
                              'descriptionPlain': 'Synthetic work'}])
        result = self.runner([SourceConfig('lever', 'synthetic', 'Synthetic', True)], transport).run()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['counts']['new'], 1)
        self.assertEqual(result['sources'][0]['requests'], 2)
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_request_budget_is_shared_across_boards_in_same_run(self):
        self.policy = RequestPolicy(max_requests=1, max_retries=0, min_interval=0)
        calls = []
        def transport(url, timeout, max_bytes):
            calls.append(url)
            return response(body())
        result = self.runner([SourceConfig('greenhouse', 'synthetic', 'Synthetic', True),
                              SourceConfig('greenhouse', 'other', 'Other', True)], transport).run()
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['counts']['new'], 1)
        self.assertEqual(result['sources'][1]['issues'], ['request_limit'])

    def test_deadline_retains_committed_jobs_and_records_terminal_summary(self):
        from jobsearch_assistant.runtime_control import RunControl
        ticks = [0]
        control = RunControl(1, monotonic=lambda: ticks[0])
        calls = []
        self.policy = RequestPolicy(max_retries=0, min_interval=0, page_size=1, max_pages=2)
        def transport(url, timeout, max_bytes):
            calls.append(url)
            if len(calls) == 2:
                self.assertEqual(len(self.database.list_vacancies()), 1)
                ticks[0] = 2
            return response([{'id': 'one', 'text': 'Junior Python', 'categories': {},
                              'hostedUrl': 'https://jobs.lever.co/synthetic/one'}])
        result = self.runner([SourceConfig('lever', 'synthetic', 'Synthetic', True)], transport, control=control).run()
        self.assertEqual(result['status'], 'deadline')
        self.assertEqual(result['counts']['new'], 1)


if __name__ == '__main__':
    unittest.main()
