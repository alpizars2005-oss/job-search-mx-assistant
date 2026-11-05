"""N-02: two calendar activations share one immutable 14:00 report date."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from jobsearch_assistant.automation_store import AutomationStore
from jobsearch_assistant.cli import build_parser, main
from jobsearch_assistant.daily_reports import DailyReports, ReportSchedule
from jobsearch_assistant.database import ApplicationDatabase
from jobsearch_assistant.runtime_control import RunLock


class ReportRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.database = ApplicationDatabase(self.home / 'applications.sqlite3')
        self.policy = patch.dict(os.environ, {'JOB_SEARCH_ASSISTANT_HOME': str(self.home),
            'DRY_RUN': 'true', 'AUTO_SUBMIT': 'false'})
        self.policy.start()
        self.addCleanup(self.policy.stop)

    def report(self, instant):
        def reporter(home, *, schedule):
            return DailyReports(home, schedule=schedule, now=lambda: datetime.fromisoformat(instant))
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch(
                'jobsearch_assistant.daily_report_cli.DailyReports', side_effect=reporter):
            with self.assertRaises(SystemExit) as caught:
                main(['reports', 'generate'])
        return caught.exception.code, out.getvalue(), err.getvalue()

    def restarted_report(self, instant):
        code = '''import sys
from datetime import datetime
from unittest.mock import patch
from jobsearch_assistant.daily_reports import DailyReports
from jobsearch_assistant.cli import main
now=datetime.fromisoformat(sys.argv[1])
def reporter(home, *, schedule):
    return DailyReports(home,schedule=schedule,now=lambda:now)
with patch('jobsearch_assistant.daily_report_cli.DailyReports',side_effect=reporter):
    main(['reports','generate'])
'''
        import jobsearch_assistant.daily_reports as module
        environment = {**os.environ, 'PYTHONPATH': str(Path(module.__file__).parents[1])}
        result = subprocess.run([sys.executable, '-c', code, instant],
            env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def contents(self, day):
        return {path.name: path.read_bytes() for path in (self.home / 'reports' / day).iterdir()}

    def test_search_at_1400_blocks_report_then_1415_keeps_original_cutoff(self):
        store = AutomationStore(self.database)
        with RunLock(self.home / 'automation.lock', budget_seconds=600):
            with patch('jobsearch_assistant.automation_store.timestamp',
                       return_value='2026-11-05T20:00:00+00:00'):
                run = store.start('synthetic', 'synthetic')
            code, out, err = self.report('2026-11-05T20:00:00+00:00')
            self.assertEqual(code, 3)
            self.assertEqual(out, '')
            self.assertIn('run_locked', err)
            self.assertFalse((self.home / 'reports' / '2026-11-05').exists())
            store.finish(run, 'success', [])
        result = self.restarted_report('2026-11-05T20:15:00+00:00')
        self.assertEqual(result['generated'], ['2026-11-05'])
        report = DailyReports(self.home).read('2026-11-05')
        self.assertEqual(report['scheduled_at'], '14:00')
        self.assertEqual(report['window']['end'], '2026-11-05T20:00:00+00:00')
        self.assertEqual(report['delay_seconds'], 900)
        self.assertEqual(report['summary']['confirmed_real_submissions'], 0)
        self.assertFalse(result['delivered'])

    def test_completed_report_is_reused_byte_for_byte_by_1415_new_process(self):
        self.assertEqual(self.report('2026-11-05T20:00:00+00:00')[0], 0)
        original = self.contents('2026-11-05')
        result = self.restarted_report('2026-11-05T20:15:00+00:00')
        self.assertEqual(result['generated'], [])
        self.assertEqual(result['reused'], ['2026-11-05'])
        self.assertEqual(self.contents('2026-11-05'), original)
        self.assertEqual(len(list((self.home / 'reports').glob('2026-11-05'))), 1)

    def test_restart_recovers_missed_day_and_concurrent_report_stays_blocked(self):
        self.assertEqual(self.report('2026-11-04T20:00:00+00:00')[0], 0)
        original = self.contents('2026-11-04')
        with RunLock(self.home / 'automation.lock'):
            self.assertEqual(self.report('2026-11-05T20:00:00+00:00')[0], 3)
            self.assertEqual(self.report('2026-11-05T20:15:00+00:00')[0], 3)
        result = self.restarted_report('2026-11-06T20:15:00+00:00')
        self.assertEqual(result['generated'], ['2026-11-05', '2026-11-06'])
        self.assertEqual(result['remaining'], 0)
        self.assertEqual(self.contents('2026-11-04'), original)
        self.assertTrue(DailyReports(self.home).read('2026-11-05')['delayed'])

    @unittest.skipUnless(os.name == 'posix' and shutil.which('systemd-analyze'),
                         'Linux systemd calendar parser')
    def test_static_and_rendered_timer_retry_today_after_first_activation(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('retry_production_manage',
            root / 'scripts' / 'production' / 'manage.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        layout = {name: self.home / name for name in ('code', 'state', 'config', 'logs', 'backups', 'units')}
        units = module.render_units(layout, 'jobsearch-assistant')
        rendered = units['jobsearch-report.timer']
        static = (root / 'deploy' / 'systemd' / 'jobsearch-report.timer').read_text(encoding='utf-8')
        import shlex
        for service in (units['jobsearch-report.service'],
                (root / 'deploy' / 'systemd' / 'jobsearch-report.service').read_text(encoding='utf-8')):
            command = next(line.split('=', 1)[1] for line in service.splitlines()
                           if line.startswith('ExecStart='))
            args = build_parser().parse_args(shlex.split(command)[1:])
            schedule = ReportSchedule(args.timezone, args.at)
            self.assertEqual(schedule.window(date(2026, 11, 5))[1],
                             datetime(2026, 11, 5, 20, 0, tzinfo=timezone.utc))
        for kind, timer in (('rendered', rendered), ('static', static)):
            next_events = []
            for line in timer.splitlines():
                if line.startswith('OnCalendar='):
                    expression = line.split('=', 1)[1]
                    result = subprocess.run(['systemd-analyze', 'calendar', '--iterations=1',
                        # Older analyze versions accept UTC timestamps here;
                        # keep the calendar expression itself in Mexico City.
                        '--base-time=2026-11-05 20:01:00 UTC', expression],
                        capture_output=True, text=True, timeout=10,
                        env={**os.environ, 'TZ': 'UTC', 'LC_ALL': 'C'})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    next_line = next(value for value in result.stdout.splitlines() if 'Next elapse:' in value)
                    value = next_line.split('Next elapse:', 1)[1].strip()
                    next_events.append(datetime.strptime(value, '%a %Y-%m-%d %H:%M:%S UTC').replace(tzinfo=timezone.utc))
            with self.subTest(kind=kind):
                self.assertTrue(next_events)
                self.assertEqual(sorted(next_events), [
                    datetime(2026, 11, 5, 20, 15, tzinfo=timezone.utc),
                    datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)])


if __name__ == '__main__':
    unittest.main()
