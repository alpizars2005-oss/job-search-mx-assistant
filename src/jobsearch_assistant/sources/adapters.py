from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl

from .http import strict_url
from .models import NormalizedJob, RequestPolicy, SourceConfig, SourceError

_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
JOB_HOSTS = {
    'greenhouse': {'boards.greenhouse.io', 'job-boards.greenhouse.io'},
    'lever': {'jobs.lever.co'},
    'ashby': {'jobs.ashbyhq.com'},
}


def endpoint(config: SourceConfig, policy: RequestPolicy, offset: int = 0) -> str:
    if config.provider == 'greenhouse':
        return f'https://boards-api.greenhouse.io/v1/boards/{config.board}/jobs?content=true'
    if config.provider == 'lever':
        return (f'https://api.lever.co/v0/postings/{config.board}'
                f'?mode=json&skip={offset}&limit={policy.page_size}')
    return f'https://api.ashbyhq.com/posting-api/job-board/{config.board}'


def _text(value, maximum=1_000_000) -> str | None:
    if value is None:
        return None
    if (not isinstance(value, str) or len(value) > maximum
            or any(ord(c) < 32 and c not in '\n\r\t' for c in value)):
        raise SourceError('invalid_record')
    return value.strip() or None


def _object(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SourceError('invalid_record')
    return value


def _list(value) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 5000:
        raise SourceError('invalid_record')
    return value


def _identifier(value) -> str:
    if type(value) is int and value > 0:
        value = str(value)
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise SourceError('invalid_record')
    return value


class _PlainText(HTMLParser):
    """Extract text only; never render, execute, or resolve links and resources."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'template', 'iframe', 'object'}:
            self.blocked += 1
        if not self.blocked and tag in {'p', 'br', 'li', 'div', 'h1', 'h2', 'h3'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'template', 'iframe', 'object'}:
            self.blocked = max(0, self.blocked - 1)
        if not self.blocked and tag in {'p', 'li', 'div'}:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def _plain(value) -> str | None:
    value = _text(value)
    if value is None:
        return None
    parser = _PlainText()
    parser.feed(html.unescape(value))
    parser.close()
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines()
                     if line.strip()) or None


def _job_url(config: SourceConfig, value, job_id: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, job_id
    try:
        parsed = strict_url(value, JOB_HOSTS[config.provider])
        parts = parsed.path.split('/')
        expected = 4 if config.provider == 'greenhouse' else 3
        if len(parts) != expected or parts[1] != config.board:
            raise SourceError('unsafe_url')
        if config.provider == 'greenhouse' and parts[2] != 'jobs':
            raise SourceError('unsafe_url')
        identity = _identifier(parts[-1])
        if job_id is not None and identity != job_id:
            raise SourceError('unsafe_url')
        for key, val in parse_qsl(parsed.query, strict_parsing=True, max_num_fields=20):
            if (not (key.startswith('utm_') or key in {'gh_src', 'source', 'lever-source', 'lever-origin'})
                    or not re.fullmatch(r'[A-Za-z0-9._~ -]{0,200}', val)):
                raise SourceError('unsafe_url')
    except (SourceError, ValueError):
        raise SourceError('unsafe_job_url') from None
    return value, identity


def _date(value) -> str | None:
    value = _text(value, 100)
    if value is None:
        return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError
        return date.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        raise SourceError('invalid_record') from None


def _mode(value, remote=None) -> str:
    if remote is not None and type(remote) is not bool:
        raise SourceError('invalid_record')
    value = (_text(value, 100) or '').casefold()
    mode = {'remote': 'remote', 'hybrid': 'hybrid', 'onsite': 'onsite',
            'on-site': 'onsite'}.get(value, 'unknown')
    if remote is True and mode not in {'remote', 'unknown'}:
        return 'unknown'
    if remote is False and mode == 'remote':
        return 'unknown'
    return 'remote' if mode == 'unknown' and remote is True else mode


def _present_path(item: dict, path: str) -> bool:
    current = item
    # Paths are generated by the adapter, never supplied by a remote document.
    for part in path.partition(':')[0].replace('[', '.').replace(']', '').split('.'):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdecimal() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    return True


def _normalize(config: SourceConfig, item: dict, request_url: str,
               index: int, retrieved_at: str) -> NormalizedJob | None:
    provider = config.provider
    prefix = f'{request_url}#' + (f'[{index}]' if provider == 'lever' else f'jobs[{index}]')
    fields: dict[str, list[str]] = {}

    def origins(name, *paths):
        fields[name] = [(f'{prefix}.{path}' if _present_path(item, path) else f'missing:{path}')
                        for path in paths]

    if provider == 'ashby':
        listed = item.get('isListed')
        if listed is not None and type(listed) is not bool:
            raise SourceError('invalid_record')
        if listed is False:
            return None
        url, identity = _job_url(config, item.get('jobUrl'), None)
        if identity is None:
            raise SourceError('invalid_record')
        title = _text(item.get('title'), 1000)
        raw_locations = [_text(item.get('location'), 5000)]
        paths = ['location']
        for i, location in enumerate(_list(item.get('secondaryLocations'))):
            raw_locations.append(_text(_object(location).get('location'), 5000))
            paths.append(f'secondaryLocations[{i}].location')
        mode = _mode(item.get('workplaceType'), item.get('isRemote'))
        plain_key = 'descriptionPlain' if item.get('descriptionPlain') is not None else 'descriptionHtml'
        description = (_text(item.get(plain_key)) if plain_key == 'descriptionPlain'
                       else _plain(item.get(plain_key)))
        published = _date(item.get('publishedAt'))
        origins('source_job_id', 'jobUrl:path_identity')
        origins('title', 'title')
        origins('url', 'jobUrl')
        origins('description', plain_key)
        origins('published_at', 'publishedAt')
        origins('work_mode', 'workplaceType', 'isRemote')
    elif provider == 'greenhouse':
        identity = _identifier(item.get('id'))
        url, _ = _job_url(config, item.get('absolute_url'), identity)
        title = _text(item.get('title'), 1000)
        raw_locations = [_text(_object(item.get('location')).get('name'), 5000)]
        paths = ['location.name']
        mode, description = 'unknown', _plain(item.get('content'))
        published = _date(item.get('first_published'))
        for name, path in [('source_job_id', 'id'), ('title', 'title'), ('url', 'absolute_url'),
                           ('description', 'content'), ('published_at', 'first_published')]:
            origins(name, path)
        fields['work_mode'] = ['policy:not_inferred_from_text']
    else:
        identity = _identifier(item.get('id'))
        url, _ = _job_url(config, item.get('hostedUrl'), identity)
        title = _text(item.get('text'), 1000)
        categories = _object(item.get('categories'))
        raw_locations = [_text(categories.get('location'), 5000)]
        paths = ['categories.location']
        for i, location in enumerate(_list(categories.get('allLocations'))):
            raw_locations.append(_text(location, 5000))
            paths.append(f'categories.allLocations[{i}]')
        mode = _mode(item.get('workplaceType'))
        key = 'descriptionPlain' if item.get('descriptionPlain') is not None else 'description'
        parts = [_text(item.get(key)) if key == 'descriptionPlain' else _plain(item.get(key))]
        description_paths = [key]
        for i, section in enumerate(_list(item.get('lists'))):
            section = _object(section)
            parts.extend([_text(section.get('text'), 1000), _plain(section.get('content'))])
            description_paths.extend([f'lists[{i}].text', f'lists[{i}].content'])
        key = 'additionalPlain' if item.get('additionalPlain') is not None else 'additional'
        parts.append(_text(item.get(key)) if key == 'additionalPlain' else _plain(item.get(key)))
        description_paths.append(key)
        description = '\n\n'.join(p for p in parts if p) or None
        published = None  # The documented list contract does not promise a publication field.
        origins('source_job_id', 'id')
        origins('title', 'text')
        origins('url', 'hostedUrl')
        origins('description', *description_paths)
        origins('work_mode', 'workplaceType')
        fields['published_at'] = ['policy:not_provided_by_documented_endpoint']
    origins('locations', *paths)
    locations = list(dict.fromkeys(location for location in raw_locations if location))
    fields.update({'source': ['configuration.provider'], 'source_board': ['configuration.board'],
                   'company': ['configuration.company'], 'retrieved_at': ['client:retrieval_time'],
                   'verification_status': ['policy:listing_completeness'],
                   'eligibility_evidence': ['policy:requires_separate_eligibility_verification']})
    complete = bool(title and description and url and locations)
    evidence = {'status': 'unknown', 'country_code': 'MX',
                'observations': {'locations': locations, 'work_mode': mode},
                'provenance': {'locations': fields['locations'], 'work_mode': fields['work_mode']}}
    return NormalizedJob(provider, config.board, identity, config.company, title, locations,
                         mode, url, description, published, retrieved_at,
                         'listed' if complete else 'incomplete', evidence, fields)


@dataclass
class ParsedPage:
    jobs: list[NormalizedJob]
    raw_count: int
    rejected: int
    issues: list[str]


def parse_page(config: SourceConfig, payload, request_url: str, retrieved_at: str) -> ParsedPage:
    if config.provider == 'lever':
        rows = payload
    elif isinstance(payload, dict) and 'jobs' in payload:
        rows = payload['jobs']
    else:
        raise SourceError('invalid_payload')
    if not isinstance(rows, list) or len(rows) > 5000:
        raise SourceError('invalid_payload')
    jobs, issues, rejected = [], [], 0
    for index, item in enumerate(rows):
        try:
            if not isinstance(item, dict):
                raise SourceError('invalid_record')
            job = _normalize(config, item, request_url, index, retrieved_at)
            if job is not None:
                jobs.append(job)
        except SourceError as error:
            rejected += 1
            if error.code not in issues:
                issues.append(error.code)
    if rows and rejected == len(rows):
        raise SourceError(issues[0], rejected=rejected)
    return ParsedPage(jobs, len(rows), rejected, issues)
