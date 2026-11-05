#!/usr/bin/env python3
"""Build an offline wheel from an exact reviewed Git commit, never the worktree."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath


class BuildError(ValueError):
    pass


def _command(argv, *, cwd=None, env=None):
    try:
        return subprocess.run(list(map(str, argv)), cwd=cwd, check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=180, env=env).stdout
    except (OSError, subprocess.SubprocessError):
        raise BuildError('offline_build_command_failed') from None


def extract_archive(archive, destination):
    """No extractall: reject links/devices, duplicate paths, traversal and excess."""
    destination = Path(destination)
    size, names = 0, set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as stream:
        for member in stream:
            name = member.name.rstrip('/')
            relative = PurePosixPath(name)
            if (not name or relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name
                    or name in names or not (member.isdir() or member.isfile())):
                raise BuildError('unsafe_source_archive')
            names.add(name)
            size += member.size
            if size > 64 * 1024 * 1024 or len(names) > 10000:
                raise BuildError('source_archive_limit')
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                contents = stream.extractfile(member)
                if contents is None:
                    raise BuildError('unsafe_source_archive')
                with target.open('xb') as output:
                    os.chmod(target, 0o600)
                    output.write(contents.read())


def schema_from_source(source):
    try:
        syntax = ast.parse((Path(source) / 'src/jobsearch_assistant/migrations.py').read_text())
        for node in syntax.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'SCHEMA_VERSION'
                    and isinstance(node.value, ast.Constant) and type(node.value.value) is int):
                return node.value.value
    except (OSError, ValueError, SyntaxError):
        pass
    raise BuildError('missing_source_schema')


def build(repo, commit, output, toolchain, *, runner=_command):
    if not isinstance(commit, str) or re.fullmatch(r'[a-f0-9]{40}', commit) is None:
        raise BuildError('exact_reviewed_commit_required')
    try:
        actual = {name: importlib.metadata.version(name) for name in ('pip', 'setuptools', 'wheel')}
    except importlib.metadata.PackageNotFoundError:
        raise BuildError('approved_build_toolchain_unavailable') from None
    if actual != toolchain:
        raise BuildError('approved_build_toolchain_mismatch')
    verified = runner(['git', '-C', str(repo), 'rev-parse', '--verify', commit + '^{commit}']).decode().strip()
    if verified != commit:
        raise BuildError('exact_reviewed_commit_required')
    archive = runner(['git', '-C', str(repo), 'archive', '--format=tar', commit])
    epoch = runner(['git', '-C', str(repo), 'show', '-s', '--format=%ct', commit]).decode().strip()
    if re.fullmatch(r'[0-9]{1,12}', epoch) is None:
        raise BuildError('invalid_commit_timestamp')
    output = Path(output)
    if os.path.lexists(output):
        raise BuildError('new_output_directory_required')
    output.mkdir(mode=0o700)
    os.chmod(output, 0o700)
    source, wheels = output / 'source', output / 'wheels'
    source.mkdir(mode=0o700)
    wheels.mkdir(mode=0o700)
    extract_archive(archive, source)
    schema = schema_from_source(source)
    runner([sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-deps', '--no-build-isolation',
            '--disable-pip-version-check', '--wheel-dir', str(wheels), str(source)],
           env={**os.environ, 'PIP_NO_INDEX': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
                'PYTHONHASHSEED': '0', 'SOURCE_DATE_EPOCH': epoch})
    candidates = list(wheels.glob('job_search_assistant-*.whl'))
    if len(candidates) != 1:
        raise BuildError('unexpected_build_artifacts')
    wheel = candidates[0]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    manifest = {'format': 1, 'project': 'job-search-assistant', 'commit': commit,
                'wheel': wheel.name, 'sha256': digest, 'schema_version': schema, 'python': '3.11'}
    provenance = {'commit': commit, 'source_archive_sha256': hashlib.sha256(archive).hexdigest(),
                  'toolchain': actual, 'build_python': platform.python_version(),
                  'runtime_target': 'Debian12/Python3.11', 'source_date_epoch': epoch,
                  'network_used_by_script': False}
    for name, value in (('manifest.json', manifest), ('provenance.json', provenance)):
        path = wheels / name
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
        path.chmod(0o600)
    wheel.chmod(0o600)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    for name in ('pip', 'setuptools', 'wheel'):
        parser.add_argument('--' + name + '-version', required=True,
                            help='Exact already-installed approved build tool version; no downloads')
    args = parser.parse_args(argv)
    try:
        toolchain = {name: getattr(args, name + '_version') for name in ('pip', 'setuptools', 'wheel')}
        result = build(args.repo, args.commit, args.output, toolchain)
        print(json.dumps({'status': 'built', 'commit': result['commit'], 'wheel_sha256': result['sha256']}))
        return 0
    except (BuildError, OSError, ValueError, tarfile.TarError, importlib.metadata.PackageNotFoundError) as error:
        code = str(error) if isinstance(error, BuildError) else 'offline_build_storage_or_toolchain_error'
        print(json.dumps({'status': 'error', 'code': code}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
