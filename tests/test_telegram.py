import io
import json
import unittest
from typing import ClassVar
from unittest.mock import patch
from urllib.error import HTTPError

from jobsearch_assistant.telegram import (
    TelegramConfig,
    TelegramTransport,
    format_event,
    load_telegram_config,
)

TOKEN = '123456:' + 'A' * 35


class TelegramTests(unittest.TestCase):
    def test_environment_is_disabled_by_default_and_secrets_are_redacted(self):
        self.assertFalse(load_telegram_config({}).enabled)
        config = load_telegram_config({'JOBSEARCH_TELEGRAM_ENABLED': 'true',
                                      'JOBSEARCH_TELEGRAM_TOKEN': TOKEN,
                                      'JOBSEARCH_TELEGRAM_CHAT_ID': '-123456'})
        self.assertTrue(config.enabled)
        self.assertTrue(config.configured)
        self.assertNotIn(TOKEN, repr(config))
        self.assertNotIn('-123456', repr(config))
        self.assertFalse(load_telegram_config({'JOBSEARCH_TELEGRAM_ENABLED': 'true'}).configured)

    def test_invalid_config_errors_never_contain_values(self):
        for options in ({'token': 'private-cv/../sendDocument'}, {'chat_id': 'private-cv'},
                        {'enabled': 1}, {'min_interval': 3}, {'max_messages': 0},
                        {'max_attempts': True}, {'budget_seconds': float('inf')},
                        {'budget_seconds': 10 ** 1000},
                        {'timeout': False}, {'max_response_bytes': 0}):
            with self.subTest(options=options), self.assertRaises(ValueError) as error:
                TelegramConfig(**options)
            self.assertNotIn('private-cv', str(error.exception))
        with self.assertRaises(ValueError):
            load_telegram_config({'JOBSEARCH_TELEGRAM_ENABLED': 'private-cv'})

    def test_messages_are_static_bilingual_labels_plus_integer_counts_ids(self):
        kinds = ('priority', 'review_pending', 'eligibility_pending',
                 'source_error', 'recovered', 'run_summary')
        for kind in kinds:
            for language in ('es', 'en'):
                text = format_event(kind, entity_id=42, count=3, language=language)
                self.assertIn('42', text)
                self.assertIn('3', text)
                self.assertLess(len(text), 4096)
                self.assertNotIn('https:', text)
        self.assertNotEqual(format_event('priority'), format_event('priority', language='en'))
        for options in ({'kind': 'private-cv'}, {'entity_id': 'private-cv'}, {'count': 'private-cv'}):
            with self.assertRaises(ValueError):
                format_event(**{'kind': 'priority', **options})

    def test_real_transport_builds_post_only_fixed_endpoint_and_rejects_redirects(self):
        config = TelegramConfig(enabled=True, token=TOKEN, chat_id='123456')
        error = HTTPError('https://api.telegram.org/', 302, 'private-cv',
                          {'Location': 'https://evil.invalid'}, io.BytesIO(b'{}'))
        with patch('jobsearch_assistant.telegram.build_opener') as build:
            build.return_value.open.side_effect = error
            result = TelegramTransport()(config, 'Resumen: 1', 2, 100)
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.full_url, f'https://api.telegram.org/bot{TOKEN}/sendMessage')
        payload = json.loads(request.data)
        self.assertEqual(payload['text'], 'Resumen: 1')
        self.assertFalse(payload['allow_paid_broadcast'])
        self.assertTrue(payload['link_preview_options']['is_disabled'])
        self.assertNotIn('parse_mode', payload)
        redirect = build.call_args.args[0]
        self.assertIsNone(redirect.redirect_request(None, None, 302, '', {}, 'https://evil.invalid'))
        self.assertEqual(result.status, 302)

    def test_transport_reads_bounded_success_and_error_body(self):
        class FakeResponse(io.BytesIO):
            status = 200
            headers: ClassVar = {'Content-Type': 'application/json'}
        config = TelegramConfig(enabled=True, token=TOKEN, chat_id='123456')
        for status in (200, 429):
            body = FakeResponse(b'x' * 1000)
            with patch('jobsearch_assistant.telegram.build_opener') as build:
                if status == 200:
                    build.return_value.open.return_value = body
                else:
                    build.return_value.open.side_effect = HTTPError('', 429, '', body.headers, body)
                result = TelegramTransport()(config, 'Resumen: 1', 2, 100)
            self.assertEqual(len(result.body), 101)
            self.assertTrue(body.closed)

    def test_transport_missing_configuration_never_constructs_network(self):
        with patch('jobsearch_assistant.telegram.build_opener') as build, self.assertRaises(ValueError):
            TelegramTransport()(TelegramConfig(enabled=True), 'Resumen: 1', 2, 100)
        build.assert_not_called()

    def test_transport_exception_never_includes_secret_or_response_text(self):
        config = TelegramConfig(enabled=True, token=TOKEN, chat_id='123456')
        with patch('jobsearch_assistant.telegram.build_opener') as build:
            build.return_value.open.side_effect = OSError(f'{TOKEN} private-cv')
            with self.assertRaises(ValueError) as caught:
                TelegramTransport()(config, 'Resumen: 1', 2, 100)
        self.assertEqual(str(caught.exception), 'telegram_transport_error')
        self.assertNotIn(TOKEN, repr(caught.exception))


if __name__ == '__main__':
    unittest.main()
