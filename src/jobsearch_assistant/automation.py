"""Finite one-shot discovery; no scheduler, CV generation, approval or submission."""
from __future__ import annotations

from dataclasses import asdict

from .automation_store import AutomationStore, safe_reports
from .sources.discovery import DiscoveryEngine
from .sources.http import SafeHttpClient
from .sources.models import SourceError
from .workflow_contracts import WorkflowError, content_digest, require_dry_run


class AutomationRunner:
    """Call only under the workspace RunLock; each page commits as it arrives."""

    def __init__(self, database, profile, configs, policy, *, control, client=None,
                 language='es', log=None):
        self.database, self.profile, self.configs = database, profile, configs
        self.policy, self.control, self.language = policy, control, language
        self.store = AutomationStore(database, language=language)
        self.client = client or SafeHttpClient(policy, control=control)
        self.log = log or (lambda record: None)

    def run(self):
        require_dry_run()
        if any(config.enabled for config in self.configs):
            with self.database._connection() as connection:
                quarantine = connection.execute("SELECT value FROM meta WHERE key='source_review_required'").fetchone()
                if quarantine and quarantine[0] != '0':
                    raise WorkflowError('source_review_required')
        config_hash = content_digest({'sources': [asdict(c) for c in self.configs],
                                      'limits': asdict(self.policy)})
        run_id = self.store.start(config_hash, content_digest(self.profile.to_dict()))
        self.log({'event': 'run_started', 'run_id': run_id})
        reports, status = [], 'success'

        def observed(job):
            self.control.check()
            item = self.store.observe(run_id, job, self.profile)
            self.log({'event': 'observation', 'run_id': run_id, **item})

        def reported(report):
            safe = safe_reports([asdict(report)])[0]
            reports.append(safe)
            self.log({'event': 'source_finished', 'run_id': run_id, **safe})

        try:
            self.client.import_state(self.store.load_http_state())
            self.client.state_callback = self.store.save_http_state
            DiscoveryEngine(self.client).run(self.configs, on_job=observed, on_report=reported)
            self.control.check()
            if any(r['status'] not in ('ok', 'disabled') for r in reports):
                status = 'partial'
        except SourceError as error:
            if error.code not in ('run_deadline', 'run_cancelled'):
                self.store.finish(run_id, 'failed', reports)
                raise
            status = 'deadline' if error.code == 'run_deadline' else 'interrupted'
        except BaseException:
            # Best effort: disk failure can leave running; next lock holder recovers.
            self.store.finish(run_id, 'failed', reports)
            raise
        result = self.store.finish(run_id, status, reports)
        self.log({'event': 'run_finished', 'run_id': run_id, 'status': status,
                  'counts': result['counts'], 'recovered_runs': result['recovered_runs']})
        return result
