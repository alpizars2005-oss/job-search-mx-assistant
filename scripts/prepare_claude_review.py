#!/usr/bin/env python3
"""Prepare an immutable, bounded review input; never invoke a model or PR code."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Callable, Mapping
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid


MAX_DIFF_BYTES = 96_000
MAX_JSON_BYTES = 1_000_000
MAX_FILES = 64
SHA_PATTERN = re.compile(r'[0-9a-f]{40}')
REPOSITORY_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}')
ACTOR_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}')
API_PATH_PATTERN = re.compile(
    r'/repos/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/'
    r'(?:pulls/[1-9][0-9]{0,8}|compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}|'
    r'collaborators/[A-Za-z0-9][A-Za-z0-9-]{0,38}/permission|'
    r'environments/claude-review|branches/main)'
)


class PreparationError(Exception):
    """A fixed diagnostic code without external content or credential values."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubReader:
    """GET only, public GitHub only, no redirects, retries, or external URLs."""

    def __init__(self, token: str, *, open_request: Callable | None = None):
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise PreparationError('github_token_missing')
        self._token = token
        self._open = open_request or build_opener(NoRedirect()).open

    def _get(self, path: str, accept: str, maximum: int) -> bytes:
        if not isinstance(path, str) or not API_PATH_PATTERN.fullmatch(path):
            raise PreparationError('github_path_invalid')
        url = 'https://api.github.com' + path
        request = Request(url, method='GET', headers={
            'Authorization': 'Bearer ' + self._token,
            'Accept': accept,
            'X-GitHub-Api-Version': '2026-03-10',
            'User-Agent': 'job-search-mx-review-preparator',
        })
        try:
            with self._open(request, timeout=10) as response:
                if response.status != 200 or response.geturl() != url:
                    raise PreparationError('github_response_invalid')
                media = response.headers.get('Content-Type', '').split(';', 1)[0].strip()
                expected = ('application/json', 'application/vnd.github+json') if accept.endswith('+json') else (
                    'application/vnd.github.diff', 'application/vnd.github.v3.diff', 'text/plain')
                if media not in expected:
                    raise PreparationError('github_media_invalid')
                body = response.read(maximum + 1)
                if len(body) > maximum:
                    raise PreparationError('github_response_too_large')
                return body
        except (OSError, URLError, ValueError):
            raise PreparationError('github_request_failed') from None

    def get_json(self, path: str) -> dict:
        try:
            value = json.loads(self._get(path, 'application/vnd.github+json', MAX_JSON_BYTES))
        except (ValueError, UnicodeError):
            raise PreparationError('github_json_invalid') from None
        if not isinstance(value, dict):
            raise PreparationError('github_json_invalid')
        return value

    def get_diff(self, path: str) -> bytes:
        return self._get(path, 'application/vnd.github.diff', MAX_DIFF_BYTES)


@dataclass(frozen=True)
class PreparedReview:
    manifest: dict
    prompt: str


def _selectors(repository, pr_number, head_sha, trusted_sha, actor) -> str:
    values = ((repository, REPOSITORY_PATTERN), (head_sha, SHA_PATTERN),
              (trusted_sha, SHA_PATTERN), (actor, ACTOR_PATTERN))
    if any(not isinstance(value, str) or not pattern.fullmatch(value) for value, pattern in values):
        raise PreparationError('review_selector_invalid')
    if not isinstance(pr_number, (int, str)) or isinstance(pr_number, bool):
        raise PreparationError('review_selector_invalid')
    number = str(pr_number)
    if not re.fullmatch(r'[1-9][0-9]{0,8}', number):
        raise PreparationError('review_selector_invalid')
    return number


def runtime_selection(environ: Mapping[str, str]) -> dict:
    if (environ.get('CLAUDE_REVIEW_ENABLED') != 'true'
            or environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise PreparationError('review_disabled_or_untrusted_context')
    if (environ.get('GITHUB_API_URL') != 'https://api.github.com'
            or environ.get('GITHUB_SERVER_URL') != 'https://github.com'):
        raise PreparationError('github_host_unsupported')
    if environ.get('ACTIONS_STEP_DEBUG', '').lower() == 'true':
        raise PreparationError('review_debug_logging_forbidden')
    if not environ.get('GH_TOKEN'):
        raise PreparationError('github_token_missing')
    selection = {
        'repository': environ.get('GITHUB_REPOSITORY'),
        'pr_number': environ.get('REVIEW_PR_NUMBER'),
        'head_sha': environ.get('REVIEW_HEAD_SHA'),
        'trusted_sha': environ.get('GITHUB_SHA'),
        'actor': environ.get('GITHUB_ACTOR'),
    }
    _selectors(**selection)
    return selection


def _validate_pr(pr: dict, repository: str, number: str, head_sha: str, trusted_sha: str) -> int:
    try:
        base, head = pr['base'], pr['head']
        base_repo, head_repo = base['repo'], head['repo']
        count = pr['changed_files']
        valid = (
            type(pr['number']) is int and pr['number'] == int(number)
            and pr['state'] == 'open' and base['ref'] == 'main'
            and base['sha'] == trusted_sha and head['sha'] == head_sha
            and base_repo['full_name'].lower() == repository.lower()
            and head_repo['full_name'].lower() == repository.lower()
            and head_repo['fork'] is False and base_repo['fork'] is False
            and type(base_repo['id']) is int and base_repo['id'] > 0
            and head_repo['id'] == base_repo['id']
            and type(count) is int and 1 <= count <= MAX_FILES
        )
    except (KeyError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise PreparationError('pull_request_not_reviewable')
    return count


def _validate_access(permission: dict, environment: dict, branch: dict, trusted_sha: str) -> None:
    try:
        reviewers = [rule for rule in environment['protection_rules']
                     if rule['type'] == 'required_reviewers']
        branch_policy = environment['deployment_branch_policy']
        valid = (
            permission['permission'] in ('write', 'maintain', 'admin')
            and permission['user']['type'] == 'User'
            and environment['name'] == 'claude-review'
            and len(reviewers) == 1 and reviewers[0]['prevent_self_review'] is True
            and isinstance(reviewers[0]['reviewers'], list) and len(reviewers[0]['reviewers']) > 0
            and all(item['type'] in ('User', 'Team')
                    and type(item['reviewer']['id']) is int and item['reviewer']['id'] > 0
                    for item in reviewers[0]['reviewers'])
            and branch_policy['protected_branches'] is True
            and branch_policy['custom_branch_policies'] is False
            and branch['name'] == 'main' and branch['protected'] is True
            and branch['commit']['sha'] == trusted_sha
        )
    except (KeyError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise PreparationError('review_access_or_protection_invalid')


def prepare_review(*, repository, pr_number, head_sha, trusted_sha, actor, api: GitHubReader) -> PreparedReview:
    number = _selectors(repository, pr_number, head_sha, trusted_sha, actor)
    prefix = '/repos/' + repository
    permission = api.get_json(f'{prefix}/collaborators/{actor}/permission')
    environment = api.get_json(f'{prefix}/environments/claude-review')
    branch = api.get_json(f'{prefix}/branches/main')
    _validate_access(permission, environment, branch, trusted_sha)
    pr_path = f'{prefix}/pulls/{number}'
    count = _validate_pr(api.get_json(pr_path), repository, number, head_sha, trusted_sha)
    diff = api.get_diff(f'{prefix}/compare/{trusted_sha}...{head_sha}')
    if (not isinstance(diff, bytes) or not diff or len(diff) > MAX_DIFF_BYTES
            or b'\x00' in diff or not diff.startswith(b'diff --git ')
            or sum(line.startswith(b'diff --git ') for line in diff.splitlines()) != count
            or b'GIT binary patch' in diff or b'Binary files ' in diff):
        raise PreparationError('review_diff_invalid_or_excessive')
    try:
        diff_text = diff.decode('utf-8', errors='strict')
    except UnicodeError:
        raise PreparationError('review_diff_encoding_invalid') from None
    if _validate_pr(api.get_json(pr_path), repository, number, head_sha, trusted_sha) != count:
        raise PreparationError('pull_request_changed')
    manifest = {
        'schema_version': 1,
        'status': 'prepared_not_reviewed',
        'claude_invoked': False,
        'repository': repository,
        'pull_request': int(number),
        'base_sha': trusted_sha,
        'head_sha': head_sha,
        'diff_sha256': hashlib.sha256(diff).hexdigest(),
        'diff_bytes': len(diff),
        'changed_files': count,
        'tests': 'not_executed',
        'coverage': 'bounded_text_diff_only',
    }
    prompt = json.dumps({'evidence': manifest, 'untrusted_diff': diff_text}, ensure_ascii=True)
    return PreparedReview(manifest, prompt)


def write_preparation(prepared: PreparedReview, destination: Path) -> None:
    try:
        destination.mkdir(mode=0o700, parents=False, exist_ok=False)
        for name, content in (
            ('manifest.json', json.dumps(prepared.manifest, indent=2) + '\n'),
            ('input.json', prepared.prompt + '\n'),
        ):
            with (destination / name).open('x', encoding='utf-8', newline='\n') as stream:
                os.chmod(destination / name, 0o600)
                stream.write(content)
    except OSError:
        raise PreparationError('review_output_unavailable') from None


def write_report(execution_path: Path, manifest_path: Path, destination: Path) -> None:
    """Extract only the final response, rejecting a run that exposed any tools."""
    try:
        with execution_path.open('rb') as stream:
            execution_bytes = stream.read(MAX_JSON_BYTES + 1)
        with manifest_path.open('rb') as stream:
            manifest_bytes = stream.read(MAX_JSON_BYTES + 1)
        if max(len(execution_bytes), len(manifest_bytes)) > MAX_JSON_BYTES:
            raise PreparationError('review_report_invalid')
        messages = json.loads(execution_bytes)
        manifest = json.loads(manifest_bytes)

        def contains_tool(value):
            if isinstance(value, dict):
                if value.get('type') in ('tool_use', 'tool_result', 'server_tool_use'):
                    return True
                return any(contains_tool(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_tool(item) for item in value)
            return False

        if not isinstance(messages, list) or contains_tool(messages):
            raise PreparationError('review_report_invalid')
        initializations = [item for item in messages if isinstance(item, dict)
                           and item.get('type') == 'system' and item.get('subtype') == 'init']
        results = [item for item in messages if isinstance(item, dict) and item.get('type') == 'result']
        if (len(initializations) != 1 or initializations[0].get('tools') != []
                or initializations[0].get('mcp_servers') != [] or len(results) != 1
                or results[0].get('subtype') != 'success' or results[0].get('is_error') is not False
                or not isinstance(results[0].get('result'), str)
                or not 1 <= len(results[0]['result'].encode('utf-8')) <= 64_000
                or not isinstance(manifest, dict) or manifest.get('status') != 'prepared_not_reviewed'):
            raise PreparationError('review_report_invalid')
        report = dict(manifest, status='model_output_requires_human_review', claude_invoked=True,
                      model_output_untrusted=True, tests='not_executed',
                      execution_sha256=hashlib.sha256(execution_bytes).hexdigest(),
                      report_text=results[0]['result'])
        with destination.open('x', encoding='utf-8', newline='\n') as stream:
            os.chmod(destination, 0o600)
            json.dump(report, stream, ensure_ascii=True, indent=2)
            stream.write('\n')
    except (OSError, ValueError, RecursionError):
        raise PreparationError('review_report_unavailable') from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--collect-report', type=Path, metavar='EXECUTION_FILE')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--report-output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.collect_report:
            if not args.manifest or not args.report_output or args.output_dir:
                raise PreparationError('review_arguments_invalid')
            write_report(args.collect_report, args.manifest, args.report_output)
            print('model_output_requires_human_review')
            return 0
        if not args.output_dir:
            raise PreparationError('review_arguments_invalid')
        selection = runtime_selection(os.environ)
        prepared = prepare_review(**selection, api=GitHubReader(os.environ['GH_TOKEN']))
        write_preparation(prepared, args.output_dir)
        # A random delimiter prevents diff content from injecting workflow outputs.
        if os.environ.get('GITHUB_OUTPUT'):
            delimiter = 'REVIEW_' + uuid.uuid4().hex
            while delimiter in prepared.prompt:
                delimiter = 'REVIEW_' + uuid.uuid4().hex
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                stream.write(f'prompt<<{delimiter}\n{prepared.prompt}\n{delimiter}\n')
        print(json.dumps(prepared.manifest, sort_keys=True))
        return 0
    except PreparationError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
