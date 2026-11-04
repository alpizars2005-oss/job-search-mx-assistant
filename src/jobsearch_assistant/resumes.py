"""Private immutable, evidence-backed resume storage and literal composition.

Manifests are commit markers: blobs are fsynced and published before a manifest
can become visible. Interrupted writes may leave private orphan blobs or temp
files, which are never listed or used without full integrity verification.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from .resume_documents import render_document, valid_document_text
from .sources.models import NormalizedJob
from .workflow_contracts import (
    WorkflowError,
    canonical_json,
    content_digest,
    vacancy_digest,
    vacancy_key,
)

MAX_MASTER_BYTES = 512 * 1024
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_EVIDENCE_BYTES = 100 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_KINDS = {'experience', 'project', 'certification', 'education', 'skill'}
_CHECKOUT = Path(__file__).resolve().parents[2]
_LABELS = {
    'en': {'experience': 'Experience', 'project': 'Projects',
           'certification': 'Certifications', 'education': 'Education', 'skill': 'Skills'},
    'es': {'experience': 'Experiencia', 'project': 'Proyectos',
           'certification': 'Certificaciones', 'education': 'Educación', 'skill': 'Habilidades'},
}


def _safe(function):
    @wraps(function)
    def protected(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except WorkflowError:
            raise
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            raise WorkflowError('resume_storage_error') from None
    return protected


def _require(condition: bool, code: str = 'invalid_resume_master') -> None:
    if not condition:
        raise WorkflowError(code)


def _identifier(value: object, *, digest: bool = False) -> None:
    _require(type(value) is str and bool((_DIGEST if digest else _ID).fullmatch(value)),
             'invalid_resume_id')


def _text(value: object, limit: int, *, multiline: bool = False) -> None:
    _require(valid_document_text(value) and bool(value.strip()) and len(value) <= limit
             and (multiline or '\n' not in value))


def _keys(value: object, required: set, optional: set | None = None) -> None:
    _require(type(value) is dict and required <= value.keys()
             and value.keys() <= required | (optional or set()))


def _bounded_json(value: object, limit: int) -> bytes:
    """Bound shape before JSON encoding to avoid arbitrary objects/deep recursion."""
    count = 0

    def visit(item, depth):
        nonlocal count
        count += 1
        _require(depth <= 16 and count <= 30000, 'resume_input_limit')
        if type(item) is dict:
            for key, child in item.items():
                _require(type(key) is str and len(key) <= 200, 'resume_input_limit')
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        else:
            _require(type(item) in (str, int, float, bool, type(None)), 'invalid_resume_data')
            if type(item) is str:
                _require(len(item) <= limit, 'resume_input_limit')
    visit(value, 0)
    encoded = canonical_json(value).encode('utf-8')
    _require(len(encoded) <= limit, 'resume_input_limit')
    return encoded


def _path(value: object, *, outside: bool = True) -> Path:
    _require(isinstance(value, (str, os.PathLike)), 'invalid_resume_path')
    raw = os.fspath(value)
    _require(type(raw) is str and bool(raw) and '\x00' not in raw
             and '://' not in raw and not raw.casefold().startswith(('file:', 'http:', 'https:')),
             'invalid_resume_path')
    # Check the original path as well as the normalized path: link/../file must
    # never disguise a traversal through a symlink.
    original = Path(raw).absolute()
    for component in (original, *original.parents):
        _require(not component.is_symlink(), 'unsafe_resume_path')
    result = Path(os.path.abspath(raw))
    if outside:
        _require(result != _CHECKOUT and _CHECKOUT not in result.parents,
                 'resume_path_inside_checkout')
    return result


def _read(path: Path, limit: int) -> bytes:
    path = _path(path)
    _require(stat.S_ISREG(path.lstat().st_mode), 'invalid_resume_file')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                         | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as handle:
        info = os.fstat(handle.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, 'invalid_resume_file')
        data = handle.read(limit + 1)
    _require(len(data) <= limit, 'resume_input_limit')
    return data


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'invalid_resume_manifest')
        result[key] = value
    return result


def _load(path: Path, limit: int) -> dict:
    raw = _read(path, limit)
    result = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
    _require(type(result) is dict and _bounded_json(result, limit) == raw,
             'invalid_resume_manifest')
    return result


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_master(payload: dict, *, stored: bool = False) -> None:
    _bounded_json(payload, MAX_MASTER_BYTES)
    _keys(payload, {'schema_version', 'candidate', 'evidence', 'claims'}, {'headlines'})
    _require(type(payload['schema_version']) is int and payload['schema_version'] == 1)
    candidate = payload['candidate']
    _keys(candidate, {'name', 'contact'})
    _text(candidate['name'], 200)
    _require(type(candidate['contact']) is list and len(candidate['contact']) <= 20)
    for contact in candidate['contact']:
        _text(contact, 500)
    if 'headlines' in payload:
        _keys(payload['headlines'], {'es', 'en'})
        for value in payload['headlines'].values():
            _text(value, 1000)
    _require(type(payload['evidence']) is list and len(payload['evidence']) <= 100)
    evidence_ids = set()
    total = 0
    for evidence in payload['evidence']:
        _keys(evidence, {'id', 'sha256', 'size' if stored else 'path'})
        _identifier(evidence['id'])
        _identifier(evidence['sha256'], digest=True)
        _require(evidence['id'] not in evidence_ids)
        evidence_ids.add(evidence['id'])
        if stored:
            _require(type(evidence['size']) is int and 0 <= evidence['size'] <= MAX_EVIDENCE_BYTES)
            total += evidence['size']
        else:
            _require(type(evidence['path']) is str and 0 < len(evidence['path']) <= 4096)
    _require(total <= MAX_TOTAL_EVIDENCE_BYTES, 'resume_input_limit')
    _require(type(payload['claims']) is list and len(payload['claims']) <= 200)
    claim_ids = set()
    for claim in payload['claims']:
        _keys(claim, {'id', 'kind', 'text', 'evidence_ids', 'attested'})
        _identifier(claim['id'])
        _require(claim['id'] not in claim_ids)
        claim_ids.add(claim['id'])
        _require(type(claim['kind']) is str and claim['kind'] in _KINDS)
        _keys(claim['text'], {'es', 'en'})
        for value in claim['text'].values():
            _text(value, 8192, multiline=True)
        _require(type(claim['attested']) is bool)
        references = claim['evidence_ids']
        _require(type(references) is list and len(references) <= 100)
        for reference in references:
            _identifier(reference)
            _require(reference in evidence_ids)
        _require(len(set(references)) == len(references))


def _job_snapshot(job: NormalizedJob) -> dict:
    _require(type(job) is NormalizedJob, 'invalid_resume_vacancy')
    payload = asdict(job)
    _bounded_json(payload, 1024 * 1024)
    for name in ('source', 'source_board', 'source_job_id', 'company', 'work_mode',
                 'retrieved_at', 'verification_status'):
        value = payload[name]
        _require(type(value) is str and bool(value.strip()) and len(value) <= 2000,
                 'invalid_resume_vacancy')
    for name in ('title', 'url', 'description', 'published_at'):
        value = payload[name]
        _require(value is None or type(value) is str, 'invalid_resume_vacancy')
    _require(type(job.locations) is list and len(job.locations) <= 100
             and all(type(item) is str and len(item) <= 2000 for item in job.locations),
             'invalid_resume_vacancy')
    _require(type(job.eligibility_evidence) is dict and type(job.provenance) is dict,
             'invalid_resume_vacancy')
    payload.pop('retrieved_at')
    return payload


def _compose(master: dict, language: str, claim_ids: list[str] | None) -> tuple[str, list, list]:
    _require(type(language) is str and language in _LABELS, 'invalid_resume_language')
    by_id = {claim['id']: claim for claim in master['claims']}
    if claim_ids is None:
        claim_ids = [claim['id'] for claim in master['claims']
                     if claim['attested'] and claim['evidence_ids']]
    _require(type(claim_ids) is list and len(claim_ids) <= 200, 'invalid_resume_selection')
    for identifier in claim_ids:
        _identifier(identifier)
        _require(identifier in by_id and by_id[identifier]['attested']
                 and bool(by_id[identifier]['evidence_ids']), 'unverified_resume_claim')
    _require(len(set(claim_ids)) == len(claim_ids), 'invalid_resume_selection')
    claims = [{'id': identifier, 'kind': by_id[identifier]['kind'],
               'text': by_id[identifier]['text'][language],
               'evidence_ids': list(by_id[identifier]['evidence_ids'])}
              for identifier in claim_ids]
    lines = [master['candidate']['name'], *master['candidate']['contact']]
    # Headlines remain user-owned master metadata. They have no attestation or
    # evidence references and therefore cannot contribute professional claims.
    previous = None
    for claim in claims:
        if claim['kind'] != previous:
            lines.extend(['', _LABELS[language][claim['kind']]])
        lines.append(claim['text'])
        previous = claim['kind']
    return '\n'.join(lines) + '\n', list(claim_ids), claims


class ResumeStore:
    """Local-only store. Every public read revalidates its immutable dependencies."""

    @_safe
    def __init__(self, root: Path):
        self.root = _path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ('evidence', 'masters', 'documents', 'versions'):
            directory = _path(self.root / name)
            directory.mkdir(mode=0o700, exist_ok=True)
            _require(directory.is_dir(), 'invalid_resume_path')

    def _publish(self, path: Path, data: bytes) -> bool:
        """Atomic no-clobber publication; a hard link exposes only complete bytes."""
        path = _path(path)
        _require(path.parent.is_dir(), 'invalid_resume_path')
        descriptor, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
        temporary = Path(temporary)
        try:
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                return False
            if os.name != 'nt':
                directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            return True
        finally:
            temporary.unlink(missing_ok=True)

    def _store_bytes(self, path: Path, data: bytes) -> None:
        self._publish(path, data)
        _require(_read(path, len(data)) == data, 'resume_integrity_error')

    @_safe
    def import_master(self, payload: dict, *, base_dir: Path) -> str:
        _validate_master(payload)
        base = _path(base_dir)
        _require(base.is_dir(), 'invalid_resume_path')
        # Take an independent, bounded JSON snapshot before copying any files.
        master = json.loads(canonical_json(payload))
        copied = []
        total = 0
        for evidence in master['evidence']:
            source = Path(evidence['path'])
            source = _path(source if source.is_absolute() else base / source)
            data = _read(source, MAX_EVIDENCE_BYTES)
            total += len(data)
            _require(total <= MAX_TOTAL_EVIDENCE_BYTES, 'resume_input_limit')
            _require(_digest(data) == evidence['sha256'], 'resume_evidence_integrity')
            self._store_bytes(self.root / 'evidence' / (evidence['sha256'] + '.bin'), data)
            copied.append({'id': evidence['id'], 'sha256': evidence['sha256'], 'size': len(data)})
        master['evidence'] = copied
        _validate_master(master, stored=True)
        master_id = content_digest(master)
        self._store_bytes(self.root / 'masters' / (master_id + '.json'),
                          canonical_json(master).encode('utf-8'))
        self.get_master(master_id)
        return master_id

    @_safe
    def get_master(self, master_id: str) -> dict:
        _identifier(master_id, digest=True)
        master = _load(self.root / 'masters' / (master_id + '.json'), MAX_MASTER_BYTES)
        _validate_master(master, stored=True)
        _require(content_digest(master) == master_id, 'resume_integrity_error')
        for evidence in master['evidence']:
            data = _read(self.root / 'evidence' / (evidence['sha256'] + '.bin'), MAX_EVIDENCE_BYTES)
            _require(len(data) == evidence['size'] and _digest(data) == evidence['sha256'],
                     'resume_evidence_integrity')
        return {'master_id': master_id, **master}

    @_safe
    def list_masters(self) -> list[dict]:
        _path(self.root / 'masters')
        return [self.get_master(path.stem) for path in sorted((self.root / 'masters').glob('*.json'))]

    @_safe
    def create_version(self, master_id: str, job: NormalizedJob, language: str, *,
                       claim_ids: list[str] | None = None, format: str = 'docx') -> dict:
        master = self.get_master(master_id)
        snapshot = _job_snapshot(job)
        text, selected, claims = _compose(master, language, claim_ids)
        _require(type(format) is str and format in ('txt', 'docx'), 'invalid_resume_format')
        document = render_document(text, format)
        sha256 = _digest(document)
        basis = {'master_id': master_id, 'sha256': sha256, 'language': language,
                 'format': format, 'vacancy_key': vacancy_key(job),
                 'vacancy_digest': vacancy_digest(job), 'claim_ids': selected,
                 'text': text, 'candidate_name': master['candidate']['name'],
                 'claims': claims, 'vacancy_snapshot': snapshot}
        version_id = content_digest(basis)
        metadata = {**basis, 'version_id': version_id,
                    'created_at': datetime.now(timezone.utc).isoformat(timespec='microseconds')}
        envelope = {'schema_version': 1, 'metadata': metadata,
                    'manifest_sha256': content_digest(metadata)}
        self._store_bytes(self.root / 'documents' / (sha256 + '.' + format), document)
        # First completed manifest wins. A retry never overwrites its timestamp.
        self._publish(self.root / 'versions' / (version_id + '.json'),
                      canonical_json(envelope).encode('utf-8'))
        return self.verify_version(version_id)

    @_safe
    def verify_version(self, version_id: str) -> dict:
        _identifier(version_id, digest=True)
        envelope = _load(self.root / 'versions' / (version_id + '.json'), MAX_MANIFEST_BYTES)
        _keys(envelope, {'schema_version', 'metadata', 'manifest_sha256'})
        _require(type(envelope['schema_version']) is int and envelope['schema_version'] == 1,
                 'invalid_resume_manifest')
        metadata = envelope['metadata']
        _keys(metadata, {'version_id', 'master_id', 'sha256', 'language', 'format',
                         'vacancy_key', 'vacancy_digest', 'claim_ids', 'created_at',
                         'text', 'candidate_name', 'claims', 'vacancy_snapshot'})
        _require(content_digest(metadata) == envelope['manifest_sha256'], 'resume_integrity_error')
        _require(metadata['version_id'] == version_id, 'resume_integrity_error')
        _identifier(metadata['sha256'], digest=True)
        _identifier(metadata['vacancy_digest'], digest=True)
        created = metadata['created_at']
        _require(type(created) is str and len(created) <= 40, 'invalid_resume_manifest')
        timestamp = datetime.fromisoformat(created)
        _require(timestamp.tzinfo is not None and timestamp.utcoffset().total_seconds() == 0,
                 'invalid_resume_manifest')
        basis = {key: value for key, value in metadata.items() if key not in ('version_id', 'created_at')}
        _require(content_digest(basis) == version_id, 'resume_integrity_error')
        master = self.get_master(metadata['master_id'])
        text, selected, claims = _compose(master, metadata['language'], metadata['claim_ids'])
        _require(text == metadata['text'] and selected == metadata['claim_ids']
                 and claims == metadata['claims'] and master['candidate']['name'] == metadata['candidate_name'],
                 'resume_integrity_error')
        _require(type(metadata['vacancy_snapshot']) is dict, 'invalid_resume_manifest')
        job = NormalizedJob(**metadata['vacancy_snapshot'], retrieved_at='verification')
        _require(_job_snapshot(job) == metadata['vacancy_snapshot']
                 and vacancy_key(job) == metadata['vacancy_key']
                 and vacancy_digest(job) == metadata['vacancy_digest'], 'resume_integrity_error')
        format = metadata['format']
        _require(type(format) is str and format in ('txt', 'docx'), 'invalid_resume_format')
        document = _read(self.root / 'documents' / (metadata['sha256'] + '.' + format), MAX_DOCUMENT_BYTES)
        _require(_digest(document) == metadata['sha256'] and document == render_document(text, format),
                 'resume_integrity_error')
        return metadata

    @_safe
    def list_versions(self) -> list[dict]:
        _path(self.root / 'versions')
        return [self.verify_version(path.stem) for path in sorted((self.root / 'versions').glob('*.json'))]

    @_safe
    def export_version(self, version_id, destination: Path) -> Path:
        metadata = self.verify_version(version_id)
        destination = _path(destination)
        _require(destination != self.root and self.root not in destination.parents,
                 'invalid_resume_export_path')
        document = _read(self.root / 'documents' / (metadata['sha256'] + '.' + metadata['format']),
                         MAX_DOCUMENT_BYTES)
        # Recheck bytes read for this export, after verify_version's independent read.
        _require(_digest(document) == metadata['sha256'], 'resume_integrity_error')
        _require(self._publish(destination, document), 'resume_export_exists')
        return destination
