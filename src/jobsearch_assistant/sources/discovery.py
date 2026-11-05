from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from ..runtime_control import LOCAL_CONTROL_CODES
from .adapters import endpoint, parse_page
from .http import SafeHttpClient
from .models import DiscoveryResult, SourceConfig, SourceError, SourceReport


class DiscoveryEngine:
    """Serial discovery with per-provider budgets, reports and in-memory identity."""

    def __init__(self, client: SafeHttpClient | None = None, *,
                 now: Callable = lambda: datetime.now(timezone.utc)):
        self.client = client or SafeHttpClient()
        self.now = now

    def run(self, configs: list[SourceConfig], *, on_job=None, on_report=None) -> DiscoveryResult:
        self.client.begin_run()
        jobs, reports, seen = [], [], set()
        stopped = None
        for config in configs:
            report = SourceReport(config.provider, config.board)
            reports.append(report)
            if not config.enabled:
                if on_report:
                    on_report(report)
                continue
            if stopped is not None:
                report.status = 'not_attempted'
                if on_report:
                    on_report(report)
                continue
            report.status = 'ok'
            start = self.client.request_counts.get(config.provider, 0)
            offset = 0
            pages = self.client.policy.max_pages if config.provider == 'lever' else 1
            for page_number in range(pages):
                url = endpoint(config, self.client.policy, offset)
                try:
                    # Timestamp after receiving/validating a response, not before sleeping/retries.
                    page = self.client.get_json(config.provider, url, lambda payload: parse_page(
                        config, payload, url, self.now().astimezone(timezone.utc).isoformat()))
                except SourceError as error:
                    report.rejected += error.rejected
                    provider_issue = getattr(error, 'provider_issue', None)
                    if provider_issue and provider_issue != error.code:
                        report.issues.append(provider_issue)
                    report.issues.append(error.code)
                    if error.code in LOCAL_CONTROL_CODES:
                        stopped = error
                        attempted = self.client.request_counts.get(config.provider, 0) - start
                        report.status = 'interrupted' if attempted else 'not_attempted'
                    else:
                        report.status = ('partial' if offset else
                                         'paused' if error.code in ('source_paused', 'source_suspended') else 'error')
                    break
                report.rejected += page.rejected
                for issue in page.issues:
                    if issue not in report.issues:
                        report.issues.append(issue)
                for job in page.jobs:
                    key = (job.source, job.source_board, job.source_job_id)
                    if key in seen:
                        report.duplicates += 1
                    else:
                        seen.add(key)
                        jobs.append(job)
                        if on_job:
                            try:
                                on_job(job)
                            except SourceError as error:
                                if error.code not in LOCAL_CONTROL_CODES:
                                    raise
                                stopped = error
                                report.status = 'interrupted'
                                report.issues.append(error.code)
                                break
                if stopped is not None:
                    break
                if config.provider != 'lever' or page.raw_count < self.client.policy.page_size:
                    break
                offset += page.raw_count
                if page_number + 1 == pages:
                    report.issues.append('page_limit')
            report.requests = self.client.request_counts.get(config.provider, 0) - start
            if report.issues and report.status == 'ok':
                report.status = 'partial'
            if on_report:
                on_report(report)
        if stopped is not None:
            raise stopped
        return DiscoveryResult(jobs, reports)
