"""Opt-in private document and local candidacy commands; no sender exists here."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import sqlite3
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .config import data_home, database_path, ensure_workspace, load_profile
from .database import ApplicationDatabase
from .matching import evaluate_match
from .migrations import legacy_identity
from .sources.models import NormalizedJob
from .workflow_contracts import WorkflowError, require_dry_run


def add_workflow_parsers(sub, vacancy_sub) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--language', choices=('es', 'en'), default='es')
    resumes = sub.add_parser('resumes', help='Manage private evidence-backed ES/EN resumes')
    resume_sub = resumes.add_subparsers(dest='resume_command', required=True)
    master = resume_sub.add_parser('import', parents=[common])
    master.add_argument('file', type=Path)
    resume_sub.add_parser('list', parents=[common])
    tailor = resume_sub.add_parser('tailor', parents=[common])
    tailor.add_argument('master_id')
    tailor.add_argument('--vacancy', type=int, required=True)
    tailor.add_argument('--format', choices=('txt', 'docx'), default='docx')
    tailor.add_argument('--claim', action='append', dest='claim_ids')
    verify = resume_sub.add_parser('verify', parents=[common])
    verify.add_argument('version_id')
    export = resume_sub.add_parser('export', parents=[common])
    export.add_argument('version_id')
    export.add_argument('output', type=Path)

    candidates = sub.add_parser('candidacies', help='Review drafts and consume local dry-run authorizations')
    candidate_sub = candidates.add_subparsers(dest='candidacy_command', required=True)
    create = candidate_sub.add_parser('create', parents=[common])
    create.add_argument('--vacancy', type=int, required=True)
    create.add_argument('--resume', required=True)
    create.add_argument('--content-file', type=Path)
    candidate_sub.add_parser('list', parents=[common])
    for operation in ('show', 'review', 'history'):
        child = candidate_sub.add_parser(operation, parents=[common])
        child.add_argument('id', type=int)
    edit = candidate_sub.add_parser('edit', parents=[common])
    edit.add_argument('id', type=int)
    edit.add_argument('--resume')
    edit.add_argument('--vacancy', type=int)
    edit.add_argument('--content-file', type=Path)
    approve = candidate_sub.add_parser('approve', parents=[common])
    approve.add_argument('id', type=int)
    approve.add_argument('--digest', required=True)
    simulate = candidate_sub.add_parser('simulate', parents=[common])
    simulate.add_argument('authorization_id')
    update = candidate_sub.add_parser('update', parents=[common])
    update.add_argument('id', type=int)
    from .models import VALID_STATUSES

    update.add_argument('--status', choices=VALID_STATUSES)
    update.add_argument('--notes')
    update.add_argument('--outcome')
    update.add_argument('--next-step')
    update.add_argument('--follow-up')

    manual = vacancy_sub.add_parser('import', parents=[common], help='Import a manual posting JSON without network')
    manual.add_argument('file', type=Path)


def _read_text(path: Path, limit: int) -> str:
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise WorkflowError('nonregular_input')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise WorkflowError('nonregular_input')
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise WorkflowError('input_too_large')
    return raw.decode('utf-8')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WorkflowError('invalid_json')
        result[key] = value
    return result


def _read_object(path: Path, limit: int) -> dict:
    def invalid_number(_value):
        raise WorkflowError('invalid_json')

    payload = json.loads(_read_text(path, limit), object_pairs_hook=_unique_object,
                         parse_constant=invalid_number)
    if not isinstance(payload, dict):
        raise WorkflowError('invalid_json')
    return payload


def _summary(version: dict) -> dict:
    fields = ('version_id', 'master_id', 'sha256', 'language', 'format', 'created_at',
              'vacancy_key', 'vacancy_digest', 'claim_ids')
    return {field: version[field] for field in fields if field in version}


def _job(database: ApplicationDatabase, vacancy_id: int) -> NormalizedJob:
    job = database.get_vacancy(vacancy_id)
    if job is None:
        raise WorkflowError('vacancy_not_found')
    return job


def _manual_url(value: str) -> None:
    """Validate passive metadata only. This URL is never fetched or followed."""
    if not value:
        return
    if value != value.strip() or '\\' in value or any(ord(c) < 33 for c in value):
        raise WorkflowError('invalid_manual_url')
    parts = urlsplit(value)
    hostname = parts.hostname or ''
    if (parts.scheme != 'https' or parts.username is not None or parts.password is not None
            or parts.port is not None or parts.fragment or not hostname.isascii()
            or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', hostname)
            or '.' not in hostname or hostname.endswith('.local')):
        raise WorkflowError('invalid_manual_url')
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return
    raise WorkflowError('invalid_manual_url')


def import_manual_vacancy(args, database: ApplicationDatabase) -> dict:
    data = _read_object(args.file, 2 * 1024 * 1024)
    keys = {'title', 'company', 'location', 'url', 'description'}
    if set(data) - keys or not {'title', 'company', 'description'} <= set(data):
        raise WorkflowError('invalid_manual_posting')
    for key in keys:
        value = data.get(key, '')
        maximum = 1_000_000 if key == 'description' else 2048 if key == 'url' else 500
        if (not isinstance(value, str) or len(value) > maximum
                or any(ord(c) < 32 and (key != 'description' or c not in '\n\r\t') for c in value)
                or (key in ('title', 'company', 'description') and not value.strip())):
            raise WorkflowError('invalid_manual_posting')
    _manual_url(data.get('url', ''))
    identity = legacy_identity(data.get('url', ''), data['company'], data['title'])
    source_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()
    job = NormalizedJob(
        source='manual', source_board='local', source_job_id=source_id, company=data['company'],
        title=data['title'], locations=[data['location']] if data.get('location') else [],
        work_mode='unknown', url=data.get('url') or None, description=data['description'],
        published_at=None, retrieved_at=datetime.now(timezone.utc).isoformat(),
        verification_status='manual_unverified', eligibility_evidence={'country_code': 'MX', 'status': 'unknown'},
        provenance={key: ['manual_json.' + key] for key in data})
    vacancy_id = database.upsert_vacancy(job)
    profile = load_profile()
    result = evaluate_match(profile, job)
    evaluation_id = database.save_evaluation(vacancy_id, profile, result, job=job)
    return {'vacancy_id': vacancy_id, 'evaluation_id': evaluation_id, 'source': 'manual'}


def _resumes(args, store) -> dict:
    action = args.resume_command
    if action == 'import':
        return {'master_id': store.import_master(_read_object(args.file, 512 * 1024), base_dir=args.file.parent)}
    if action == 'list':
        return {'masters': [{key: item[key] for key in ('master_id', 'created_at') if key in item}
                            for item in store.list_masters()],
                'versions': [_summary(item) for item in store.list_versions()]}
    if action == 'tailor':
        database = ApplicationDatabase(database_path())
        version = store.create_version(args.master_id, _job(database, args.vacancy), args.language,
                                       claim_ids=args.claim_ids, format=args.format)
        return _summary(version)
    if action == 'verify':
        return {'integrity_ok': True, **_summary(store.verify_version(args.version_id))}
    version = store.verify_version(args.version_id)
    if args.output.suffix.casefold() != '.' + version['format']:
        raise WorkflowError('incorrect_export_extension')
    output = store.export_version(args.version_id, args.output)
    return {'output': str(output), **_summary(version)}


def _candidacies(args, database: ApplicationDatabase, store) -> dict | list:
    from .candidacies import CandidacyWorkflow

    workflow = CandidacyWorkflow(database, store)
    action = args.candidacy_command
    if action == 'create':
        content = _read_text(args.content_file, 200_000) if args.content_file else None
        return {'candidacy_id': workflow.create(args.vacancy, args.resume, content)}
    if action == 'list':
        allowed = ('id', 'application_id', 'vacancy_id', 'resume_version_id', 'workflow_state',
                   'revision', 'status', 'created_at', 'updated_at', 'follow_up_on')
        return [{key: item[key] for key in allowed if key in item} for item in workflow.list()]
    if action == 'simulate':
        return workflow.simulate(args.authorization_id)
    current = workflow.get(args.id)
    if current is None:
        raise WorkflowError('candidacy_not_found')
    if action == 'show':
        return current
    if action == 'history':
        return workflow.history(args.id)
    if action == 'review':
        return workflow.review(args.id)
    if action == 'approve':
        return {'authorization_id': workflow.approve(args.id, args.digest)}
    if action == 'edit':
        if args.resume is None and args.vacancy is None and args.content_file is None:
            raise WorkflowError('empty_edit')
        content = _read_text(args.content_file, 200_000) if args.content_file else None
        regenerate = content is None and (args.resume is not None or args.vacancy is not None)
        changed = workflow.edit(args.id, resume_version_id=args.resume, content=content,
                                vacancy_id=args.vacancy, regenerate_content=regenerate)
        return {'candidacy_id': args.id, 'changed': changed}
    if all(value is None for value in (args.status, args.notes, args.outcome, args.next_step, args.follow_up)):
        raise WorkflowError('empty_update')
    updated = workflow.update_tracking(args.id, status=args.status, notes=args.notes, outcome=args.outcome,
                                       next_step=args.next_step, follow_up_on=args.follow_up)
    return {'candidacy_id': args.id, 'updated': updated}


class _DeferredResumes:
    """Construct/validate storage only inside the transactional CV verifier."""

    def __init__(self, root: Path):
        self.root = root

    def verify_version(self, version_id: str) -> dict:
        from .resumes import ResumeStore

        return ResumeStore(self.root).verify_version(version_id)


def dispatch_workflow(args) -> int:
    try:
        require_dry_run()
        ensure_workspace()
        if args.command == 'vacancies':
            payload = import_manual_vacancy(args, ApplicationDatabase(database_path()))
        elif args.command == 'resumes':
            from .resumes import ResumeStore

            store = ResumeStore(data_home() / 'resumes')
            payload = _resumes(args, store)
        else:
            payload = _candidacies(args, ApplicationDatabase(database_path()),
                                   _DeferredResumes(data_home() / 'resumes'))
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, sqlite3.Error) as error:
        code = error.code if isinstance(error, WorkflowError) else 'local_operation_failed'
        label = 'Falló la operación local' if args.language == 'es' else 'Local operation failed'
        print(label + ': ' + code, file=sys.stderr)
        return 2
