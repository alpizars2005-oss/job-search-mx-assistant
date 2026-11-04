import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.cli import main
from jobsearch_assistant.sources.config import load_source_config
from jobsearch_assistant.sources.models import DiscoveryResult, SourceReport


class DiscoveryCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'sources.json'
        self.environment = patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': str(self.root / 'private')})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def config(self, **updates):
        data = {'schema_version': 1, 'sources': [
            {'provider': 'greenhouse', 'board': 'example', 'company': 'Synthetic Company'}]}
        data.update(updates)
        self.path.write_text(json.dumps(data), encoding='utf-8')
        return data

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as exit_status:
                main(list(args))
        return exit_status.exception.code, stdout.getvalue(), stderr.getvalue()

    def test_defaults_and_disabled_examples_never_access_network_or_private_workspace(self):
        configs, policy = load_source_config(None)
        self.assertEqual(configs, [])
        self.assertEqual(policy.max_requests, 20)
        with patch('jobsearch_assistant.sources.http.UrllibTransport.__call__', side_effect=AssertionError('network')):
            code, output, _ = self.invoke('discover')
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output), {'jobs': [], 'reports': []})
            self.config()
            code, output, _ = self.invoke('discover', '--config', str(self.path))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)['reports'][0]['status'], 'disabled')
        self.assertFalse((self.root / 'private').exists())

    def test_explicit_configuration_and_limits_are_strict(self):
        data = self.config(limits={'timeout': 2, 'max_requests': 3})
        data['sources'][0]['enabled'] = True
        self.path.write_text(json.dumps(data))
        configs, policy = load_source_config(self.path)
        self.assertTrue(configs[0].enabled)
        self.assertEqual(policy.timeout, 2)
        self.assertEqual(policy.max_requests, 3)
        invalid = [None, [], {'schema_version': True, 'sources': []},
                   {'schema_version': 99, 'sources': []},
                   {'schema_version': 1, 'sources': 'wrong'},
                   {'schema_version': 1, 'sources': [], 'private-value': 'secret'},
                   dict(data, limits={'timeout': '2'}),
                   dict(data, limits={'max_requests': True}),
                   dict(data, limits={'base_url': 'https://127.0.0.1'}),
                   dict(data, sources=[dict(data['sources'][0], enabled='false')]),
                   dict(data, sources=[dict(data['sources'][0], board='../evil')]),
                   dict(data, sources=[dict(data['sources'][0], url='https://evil.example')]),
                   dict(data, sources=data['sources'] * 2)]
        for value in invalid:
            with self.subTest(value=value):
                self.path.write_text(json.dumps(value))
                with self.assertRaises(ValueError) as error:
                    load_source_config(self.path)
                self.assertNotIn('private-value', str(error.exception))

    def test_invalid_json_duplicate_keys_size_and_encoding(self):
        for text in ('{bad', '{"schema_version":1,"schema_version":2,"sources":[]}',
                     '{"schema_version":1,"sources":[],"limits":{"timeout":NaN}}', ' ' * 65537):
            with self.subTest(text=text[:30]):
                self.path.write_text(text)
                with self.assertRaises(ValueError):
                    load_source_config(self.path)
        self.path.write_bytes(b'\xff')
        with self.assertRaises(ValueError):
            load_source_config(self.path)

    def test_configuration_errors_are_redacted_in_both_languages(self):
        for language, message in [('es', 'Configuración de fuentes inválida'),
                                  ('en', 'Invalid source configuration')]:
            code, output, error = self.invoke('discover', '--config',
                                               str(self.root / 'private-value.json'),
                                               '--language', language)
            self.assertEqual(code, 2)
            self.assertEqual(output, '')
            self.assertIn(message, error)
            self.assertNotIn('private-value', error)

    def test_cli_serializes_success_and_signals_partial_failure_without_database(self):
        self.config()
        result = DiscoveryResult([], [SourceReport('greenhouse', 'example', status='partial',
                                                   issues=['request_limit'])])
        with patch('jobsearch_assistant.sources.discovery.DiscoveryEngine.run', return_value=result):
            code, output, error = self.invoke('discover', '--config', str(self.path))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)['reports'][0]['issues'], ['request_limit'])
        self.assertEqual(error, '')
        self.assertFalse((self.root / 'private').exists())

    def test_existing_cli_help_and_init_still_work(self):
        code, output, _ = self.invoke('--help')
        self.assertEqual(code, 0)
        for command in ('analyze', 'applications', 'gui', 'discover'):
            self.assertIn(command, output)
        code, _, _ = self.invoke('init', '--language', 'en')
        self.assertEqual(code, 0)
        self.assertTrue((self.root / 'private' / 'applications.sqlite3').is_file())

    def test_excessive_numeric_settings_return_redacted_config_error(self):
        self.config(limits={'timeout': 10 ** 400})
        code, output, error = self.invoke('discover', '--config', str(self.path))
        self.assertEqual(code, 2)
        self.assertEqual(output, '')
        self.assertEqual(error.strip(), 'Configuración de fuentes inválida')
