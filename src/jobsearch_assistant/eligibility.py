"""Conservative, deterministic eligibility rules for English/Spanish postings.

These bounded rules extract explicit statements, not general natural language
understanding. Unrecognized mandatory statements remain unknown. Source hints
and a candidate's country never establish an employer's hiring permission.
"""
from __future__ import annotations

import re
from typing import Any

from .evaluator import COMMON_TECH_SKILLS, SUSPICIOUS_TERMS, contains_phrase, normalize
from .models import CandidateProfile, JobPosting
from .sources.models import NormalizedJob

_REQUIREMENT = re.compile(r'\b(required?|requires?|must|mandatory|minimum|at least|need(?:ed)?|'
                          r'obligatori[oa]s?|indispensables?|requier[ea]|requisitos?|minimo)\b')
_PREFERRED = re.compile(r'\b(preferred?|preferably|desirable|desired|nice to have|optional|'
                        r'deseables?|preferentes?|preferiblemente|ideal|opcional)\b')
_YEARS = re.compile(r'\b(\d{1,2}(?:\.\d+)?)\s*(?:\+|[-–]\s*\d{1,2})?\s*(?:years?|anos)\b')
_DEGREE = re.compile(r"\b(?:bachelor(?:'s)?|degree|university degree|college degree|"
                     r'titulo(?: universitario)?|licenciatura|carrera terminada)\b')
_REMOTE = re.compile(r'\b(?:remote|remot[oa]|home office|work from home|work from anywhere|'
                     r'trabajo desde casa|trabajar desde casa)\b')
_NONREMOTE = re.compile(r'\b(?:on[- ]site|onsite|presencial|office[- ]based|in[- ]office|h[iy]brid[oa]?)\b')
_SENIOR = re.compile(r'\b(?:senior|sr\.?|lead|principal|manager|director|gerente)\b')
_JUNIOR = re.compile(r'\b(?:junior|jr\.?|entry[- ]level|trainee|intern(?:ship)?|associate|practicante)\b')
_LANGUAGES = {
    'english': ('english', 'ingles'), 'spanish': ('spanish', 'espanol'),
    'french': ('french', 'frances'), 'german': ('german', 'aleman'),
    'portuguese': ('portuguese', 'portugues'), 'italian': ('italian', 'italiano'),
    'japanese': ('japanese', 'japones'), 'mandarin': ('mandarin', 'chinese', 'chino'),
}
_LEVELS = {'a1': 1, 'basic': 1, 'a2': 2, 'b1': 3, 'intermediate': 3,
           'b2': 4, 'advanced': 5, 'c1': 5, 'fluent': 5, 'c2': 6, 'native': 6}
# Boundaries separate independent facts while retaining explicit degree alternatives.
_FACT_SEPARATOR = re.compile(r',(?!(?:\s*)(?:or equivalent|o experiencia equivalente))|;|'
                             r'\b(?:and|but|y|e|pero|plus|with|con|ademas de|mas|junto con)\b')
_CONDITIONS = {
    'security_clearance': r'\b(?:security clearance|clearance|habilitacion de seguridad)\b',
    'weekend_work': r'\b(?:weekends?|fines de semana)\b',
    'travel': r'\b(?:travel|viaj(?:ar|es))\b',
    'driver_license': r"\b(?:driver'?s? licen[cs]e|driving licen[cs]e|licencia de conducir)\b",
    'certification': r'\b(?:certification|certified|certificacion|certificado)\b',
}
_OTHER_COUNTRY = (r'(?:united states|estados unidos|u\.?s\.?a?\.?|ee\.?\s?uu\.?|'
                  r'canada|uk|united kingdom|reino unido|europe|europa|germany|alemania|spain|espana)')
_GEOGRAPHIC_PEOPLE = r'(?:residents?|citizens?|applicants?|candidates?)'
_GEOGRAPHIC_RESTRICTION = re.compile(
    rf'\b{_OTHER_COUNTRY}(?:[- ]based)?\s+{_GEOGRAPHIC_PEOPLE}\s+only\b|'
    rf'\b(?:only|restricted to|limited to|exclusively)\s+(?:{_GEOGRAPHIC_PEOPLE}\s+(?:of|in)\s+)(?:the\s+)?{_OTHER_COUNTRY}\b|'
    rf'\b(?:open|available)\s+only\s+to\s+(?:{_GEOGRAPHIC_PEOPLE}\s+(?:of|in)\s+(?:the\s+)?{_OTHER_COUNTRY}|'
    rf'{_OTHER_COUNTRY}\s+{_GEOGRAPHIC_PEOPLE})\b|'
    rf'\bonly\s+{_OTHER_COUNTRY}\s+{_GEOGRAPHIC_PEOPLE}\s+(?:may|can)\s+apply\b|'
    rf'\bonly\s+(?:{_OTHER_COUNTRY}[- ]based\s+{_GEOGRAPHIC_PEOPLE}|'
    rf'{_GEOGRAPHIC_PEOPLE}\s+(?:(?:who|that)\s+(?:are\s+)?)?(?:located|based|residing|living)\s+in\s+(?:the\s+)?{_OTHER_COUNTRY})\b|'
    rf'\b(?:must|have to)\s+(?:reside|live|be based|be located)\s+in\s+(?:the\s+)?{_OTHER_COUNTRY}\b|'
    rf'\b(?:must|have to)\s+be\s+(?:a\s+)?{_OTHER_COUNTRY}\s+(?:residents?|citizens?)\b|'
    rf'\b(?:this|the|current)\s+(?:[\w-]+\s+){{0,4}}(?:role|position|vacancy)\s+(?:is\s+)?{_OTHER_COUNTRY}[- ]based\b|'
    rf'\bsolo\s+(?:contratamos\s+)?(?:candidatos?\s+)?(?:residentes?|ciudadanos?)\s+(?:de|en)\s+{_OTHER_COUNTRY}\b|'
    rf'\b(?:residencia|contratacion)\s+exclusiva\s+(?:en|para\s+(?:residentes?|ciudadanos?)\s+(?:de|en))\s+{_OTHER_COUNTRY}\b')
_GEOGRAPHIC_WAIVER = re.compile(
    rf'\b{_OTHER_COUNTRY}\s+(?:residence|residency|citizenship)\s+(?:is\s+)?not\s+(?:required|needed)\b')
_REMOTE_COUNTRY_LOCATION = re.compile(
    rf'(?:remote\s*[-,:(]\s*(?:the\s+)?{_OTHER_COUNTRY}\)?|'
    rf'{_OTHER_COUNTRY}\s*[-,(]\s*remote\)?|{_OTHER_COUNTRY}\s+only)[.\s]*')
_GEOGRAPHIC_SEPARATOR = re.compile(r'[,;]|\b(?:and|but|however|y|pero|sin embargo)\b')


def _current_geographic_scope(text: str, match: re.Match) -> bool:
    """An explicit reference to another role cannot establish this vacancy's facts.

    Generic employer permission still applies unless it carries a role qualifier.
    Named role groups are left unverified; only a pointer to the current vacancy
    resolves that qualifier. Keep this independent of compatibility/title scoring.
    """
    role = r'(?:roles?|positions?|vacanc(?:y|ies)|puestos?|vacantes?)'
    current = r'\b(?:this|current|este|esta|actual)\b'

    def current_reference(value):
        if re.search(r'\b(?:other|another|otros?|otras?)\b', value):
            return False
        return bool(re.search(current, value) or re.search(
            rf'\b(?:all\s+{role}|tod[oa]s\s+(?:l[oa]s\s+)?{role})\b', value))
    # A qualifier immediately after the hiring/residence fact binds to that fact,
    # before a later clause about the current role can change the scope.
    following = re.match(r'\s+(?:for|para)\s+([^,;]{1,70})', text[match.end():])
    if following:
        qualifier = _GEOGRAPHIC_SEPARATOR.split(following.group(1))[0]
        return bool(current_reference(qualifier) and re.search(rf'\b{role}\b', qualifier))
    # Explicit "this engineering role" subjects override an earlier role's clause.
    if re.match(rf'(?:this|current|este|esta)\s+(?:[\w-]+\s+){{0,4}}{role}\b', match.group()):
        return True
    before = text[:match.start()]
    qualifier = re.search(r'\b(?:for|para)\s+([^,;]{1,70}),\s*$', before)
    if qualifier:
        return bool(current_reference(qualifier.group(1)) and re.search(rf'\b{role}\b', qualifier.group(1)))
    references = list(re.finditer(rf'\b{role}\b', before))
    if references:
        last = references[-1]
        # Bind to the most recent role reference, keeping "for sales roles, we"
        # together while dropping an earlier independent clause.
        prefix = re.split(r'[,;]|\b(?:but|pero|while|mientras)\b', before[:last.start()])[-1]
        return current_reference(prefix + before[last.start():last.end()])
    return True


def _geographic_negated(text: str, match: re.Match) -> bool:
    # "Not only US residents" explicitly rejects exclusivity. The general
    # negation helper deliberately removes "not only" for positive skill facts.
    before = text[:match.start()]
    after = text[match.end():]
    return bool(re.search(r'\b(?:not only|no solo)\s*$', before) or _negated(text, match)
                or re.match(r'\s+(?:(?:will|can|may|are|is)\s+)?not\s+(?:be\s+)?'
                            r'(?:considered|accepted|eligible|permitted|allowed)\b', after))


def _vacancy_residence_restriction(text: str, match: re.Match) -> bool:
    """Ignore premises, clients, subgroup obligations and non-hiring benefits."""
    if not _current_geographic_scope(text, match) or _geographic_negated(text, match):
        return False
    before = _GEOGRAPHIC_SEPARATOR.split(text[:match.start()])[-1]
    if re.search(r'\b(?:office|offices|client|clients|customer|customers|headquarters|oficina|oficinas|clientes?)\b', before):
        return False
    after = _GEOGRAPHIC_SEPARATOR.split(text[match.end():])[0]
    if re.match(r'\s+(?:need|must|have)\b', after):
        return False
    if re.search(r'\b(?:reimbursement|benefits?|tax forms?|w-9|relocation assistance|reembolso|beneficios?)\b', after):
        return False
    # An explicit Mexico alternative/exception means the country list does not
    # establish an incompatible residence requirement. It grants no permission.
    if re.search(r'\b(?:or|except|excepting|including|o|excepto|incluyendo)\b[^.;]{0,50}\bmexico\b', after):
        return False
    return True


def job_segments(job: JobPosting | NormalizedJob) -> list[dict[str, Any]]:
    """Keep original field offsets so evidence can be checked against the input."""
    if isinstance(job, NormalizedJob):
        fields = [('title', job.title or ''),
                  *[(f'locations[{index}]', value) for index, value in enumerate(job.locations)],
                  ('work_mode', job.work_mode), ('description', job.description or '')]
        provenance = job.provenance
    else:
        fields = [('title', job.title), ('location', job.location), ('description', job.description)]
        provenance = {}
    result = []
    separator = re.compile(r'(?<!\b[Uu]\.[Ss])\.(?=\s|$)|[;\n]')
    for name, value in fields:
        start = 0
        for end in [match.end() for match in separator.finditer(value)] + [len(value)]:
            raw = value[start:end]
            left = len(raw) - len(raw.lstrip())
            right = len(raw.rstrip())
            if raw.strip():
                field = name.split('[')[0]
                result.append({'field': name, 'start': start + left, 'end': start + right,
                               'span': raw.strip(),
                               'provenance': list(provenance.get(field, []))})
            start = end
    return result


def _text(segment: dict[str, Any]) -> str:
    return normalize(segment['span'])


def _negated(text: str, match: re.Match) -> bool:
    before = re.split(r'[,;]|\b(?:and|but|y|pero|however)\b', text[:match.start()])[-1]
    before = re.sub(r'\b(?:not only|no solo)\b', '', before)
    before = ' '.join(before.split()[-8:])
    after = text[match.end():match.end() + 40]
    return bool(re.search(r'\b(?:no|not|never|without|sin|nunca|cannot|can\x27t)\b', before)
                or re.match(r'\s+(?:(?:work|position|role|trabajo|puesto)\s+)?'
                            r'(?:(?:is|are|will be|es|son|esta)\s+)?'
                            r'(?:not required|not needed|not available|unavailable|prohibited|'
                            r'not permitted|not allowed|no esta disponible|no disponible|'
                            r'prohibid[oa]|no obligatori[oa]|no requerid[oa])\b', after))


def affirmed_phrase(segment: dict[str, Any], phrase: str) -> bool:
    """A literal mention is a positive signal only when its predicate is not negated."""
    normalized = normalize(phrase)
    if not normalized:
        return False
    text = _text(segment)
    pattern = r'(?<!\w)' + re.escape(normalized) + r'(?!\w)'
    return any(not _negated(text, match) for match in re.finditer(pattern, text))


def _local_text(text: str, match: re.Match, separator=_FACT_SEPARATOR) -> str:
    # Qualifiers bind to a conjunction/comma-separated fact, not every fact in
    # a paragraph. Keep evidence on the complete original statement.
    boundaries = list(separator.finditer(text))
    start = max((part.end() for part in boundaries if part.end() <= match.start()), default=0)
    end = min((part.start() for part in boundaries if part.start() >= match.end()), default=len(text))
    return text[start:end]


def _profile_evidence(field: str, value: Any) -> dict[str, Any]:
    return {'field': f'profile.{field}', 'value': value, 'provenance': ['candidate_profile']}


def _requirement(name: str, status: str, required: bool, reason: str,
                 evidence: list[dict[str, Any]] | None = None, **details) -> dict[str, Any]:
    return {'name': name, 'status': status, 'required': required, 'reason_code': reason,
            'evidence': evidence or [], **details}


def _combined(positive, negative, fallback='unknown'):
    if positive and negative:
        return 'contradictory'
    if negative:
        return 'unmet'
    if positive:
        return 'met'
    return fallback


def _mexico(segments):
    positive, negative, hints = [], [], []
    actor = r'we\s+(?:(?:can|are able to|are)\s+)?(?:hire|hiring|employ|engage)'
    people = r'(?:candidates?|applicants?|people|employees?|residents?|engineers?|developers?|workers?)'
    residence = (rf'{people}\s+(?:(?:who|that)\s+(?:are\s+)?)?'
                 r'(?:(?:residing|based|located|living)\s+in|from|in)\s+mexico')
    spanish_people = r'(?:candidatos?|personas?|residentes?|ingenieros?|trabajadores?)'
    spanish_residence = (rf'{spanish_people}\s+(?:(?:que\s+)?(?:residen|viven)\s+en|'
                         r'(?:residentes|radicados|ubicados)\s+en|en|desde)\s+mexico')
    # Positive permission has a bounded hiring/residence grammar. Merely finding
    # Mexico somewhere after "hire" also matches experience, offices and exclusions.
    permit = re.compile(
        rf'\b{actor}\s+(?:{residence}|(?:in|from)\s+mexico)\b|'
        rf'\b(?:contratamos|podemos contratar)\s+(?:a\s+)?(?:{spanish_residence}|(?:en|desde)\s+mexico)\b|'
        r'\b(?:hiring (?:is )?(?:permitted|allowed|supported))\s+(?:in|from)\s+mexico\b|'
        r'\bcontratacion (?:permitida|habilitada)\s+(?:en|desde)\s+mexico\b|'
        rf'\b(?:this\s+)?(?:role|position|vacancy)\s+(?:is\s+)?(?:open|available)\s+to\s+{residence}\b|'
        rf'\b{residence}\s+(?:are\s+)?(?:eligible|can apply|may apply)\b')
    deny = re.compile(
        r'\b(?:cannot|can not|can\x27t|do not|don\x27t|unable to|no podemos|no se permite)\s+'
        rf'(?:hire|employ|contratar)\s+(?:{residence}|(?:a\s+)?{spanish_residence}|(?:in|from|en|desde)\s+mexico)\b|'
        rf'\bno contratamos\s+(?:a\s+)?(?:{spanish_residence}|(?:en|desde)\s+mexico)\b|'
        r'\bhiring\s+is\s+not\s+(?:permitted|allowed|supported)\s+(?:in|from)\s+mexico\b|'
        rf'\b{people}\s+(?:(?:who|that)\s+(?:are\s+)?)?not\s+(?:based|residing|located|living)\s+in\s+mexico\b|'
        rf'\b(?:this\s+)?(?:role|position|vacancy)\s+(?:is\s+)?not\s+(?:open|available)\s+to\s+{residence}\b|'
        rf'\b{residence}\s+(?:cannot|can not|can\x27t|may not|must not)\s+apply\b|'
        rf'\b(?:(?:esta|este|la|el)\s+)?(?:vacante|puesto)\s+no\s+(?:esta|es)\s+(?:disponible|abiert[oa])\s+para\s+{spanish_residence}\b|'
        rf'\b{spanish_residence}\s+no\s+(?:pueden|podran|deben)\s+(?:aplicar|postularse|solicitar)\b|'
        r'\bmexico\s+(?:(?:is|are)\s+)?(?:excluded|not eligible|no elegible)\b')
    hiring_context = re.compile(r'\b(?:hire|hiring|employ|contratamos|contratar|contratacion)\b')
    exclusion = re.compile(r'\b(?:except|excluding|excepto|salvo|menos|not|no)\s+mexico\b')
    role_exception = re.compile(r'\b(?:except|excluding|excepto|salvo)\s+(?:this|the|este|esta)\s+(?:role|position|puesto|vacante)\b|'
                                r'\b(?:this|the)\s+(?:role|position)\s+is\s+excluded\b')
    for item in segments:
        text = _text(item)
        if re.search(r'\b(?:mexico|latam|americas|global|worldwide)\b', text):
            hints.append(item)
        denied = [match for match in deny.finditer(text)
                  if _current_geographic_scope(text, match) and not _negated(text, match)]
        excluded = [match for match in exclusion.finditer(text)
                    if hiring_context.search(text) and not _negated(text, match)]
        rejected_here = bool(denied or excluded or (permit.search(text) and role_exception.search(text)))
        if rejected_here:
            negative.append(item)
        if _REMOTE_COUNTRY_LOCATION.fullmatch(text):
            negative.append(item)
        for match in _GEOGRAPHIC_RESTRICTION.finditer(text):
            if _vacancy_residence_restriction(text, match):
                negative.append(item)
        for match in permit.finditer(text):
            local = _local_text(text, match, _GEOGRAPHIC_SEPARATOR)
            if (not _negated(text, match)
                    and _current_geographic_scope(text, match)
                    and not role_exception.search(text)
                    and not re.search(r'\b(?:hope|hoping|hoped)\b', text[:match.start()])
                    and not re.search(r'\b(?:if|subject to|provided|pending|depending|sujeto a|si se)\b', local)
                    and not re.search(r'\b(?:except|excluding|excepto|salvo)\b', local)):
                positive.append(item)
    status = _combined(positive, negative)
    reason = {'met': 'explicit_mexico_hiring_permission', 'unmet': 'explicit_geographic_exclusion',
              'contradictory': 'conflicting_hiring_restrictions', 'unknown': 'mexico_hiring_not_confirmed'}[status]
    return _requirement('mexico_hiring', status, True, reason, positive + negative or hints)


def _remote(profile, segments):
    if not profile.remote_only:
        return _requirement('remote_work', 'not_required', False, 'remote_preference_disabled')
    positive, negative, ambiguous = [], [], []
    for item in segments:
        text = _text(item)
        remote = list(_REMOTE.finditer(text))
        nonremote = [m for m in _NONREMOTE.finditer(text) if not _negated(text, m)]
        negremote = [m for m in remote if _negated(text, m)]
        if nonremote or negremote:
            negative.append(item)
        if remote and not nonremote and not negremote:
            if re.search(r'\b(?:may|might|possibly|possible|potentially|subject to|quizas|posible|podria)\b', text):
                ambiguous.append(item)
            else:
                positive.append(item)
    status = _combined(positive, negative)
    return _requirement('remote_work', status, True,
                        {'met': 'remote_confirmed', 'unmet': 'nonremote_confirmed',
                         'unknown': 'remote_not_confirmed', 'contradictory': 'conflicting_work_modes'}[status],
                        positive + negative + ambiguous)


def _experience(profile, segments):
    required, preferred, waived, scoped_required = [], [], [], []
    # A technology/role following 'experience with/in/as' belongs to the years
    # requirement; it is not a separate fact for this particular rule.
    year_separator = re.compile(r',|;|\b(?:and|but|y|pero|plus|ademas de|mas)\b')
    for item in segments:
        text = _text(item)
        if re.search(r'\b(?:no experience (?:is )?(?:required|needed)|sin experiencia|'
                     r'no se requiere experiencia)\b', text):
            waived.append(item)
            continue
        matches = list(_YEARS.finditer(text))
        if not matches or not (re.search(r'\b(?:experience|experiencia)\b', text) or _REQUIREMENT.search(text)):
            continue
        for match in matches:
            local = _local_text(text, match, year_separator)
            bucket = preferred if _PREFERRED.search(local) else required
            bucket.append((float(match.group(1)), item))
            after_years = local[_YEARS.search(local).end():]
            experience = re.search(r'\b(?:experience|experiencia)\b', after_years)
            before_experience = after_years[:experience.start()] if experience else ''
            scope_words = re.sub(r'\b(?:of|de|professional|profesional|work|laboral|relevant|relevante|prior|previous|previa)\b', '', before_experience).strip()
            specialized = (any(contains_phrase(local, skill) for skill in COMMON_TECH_SKILLS)
                           or bool(scope_words)
                           or re.search(r'\b(?:experience|experiencia)\s+(?:in|with|as|en|como|de)\s+(?!total\b)\w', after_years))
            if bucket is required and specialized:
                scoped_required.append(item)
    result = []
    for name, facts, mandatory in [('experience', required, True), ('preferred_experience', preferred, False)]:
        if not facts:
            if mandatory:
                result.append(_requirement(name, 'not_required', False, 'no_mandatory_experience_found', waived))
            continue
        minimum = max(years for years, _ in facts)
        if mandatory and waived:
            status = 'contradictory'
        elif profile.experience_years is None:
            status = 'unknown'
        else:
            status = 'met' if profile.experience_years >= minimum else 'unmet'
        reason = {'met': 'experience_sufficient', 'unmet': 'experience_below_minimum',
                  'unknown': 'candidate_experience_unknown', 'contradictory': 'conflicting_experience_requirements'}[status]
        evidence = [item for _, item in facts] + waived
        if profile.experience_years is not None:
            evidence.append(_profile_evidence('experience_years', profile.experience_years))
        result.append(_requirement(name, status, mandatory, reason, evidence, minimum_years=minimum))
    if scoped_required:
        result.append(_requirement('scoped_experience', 'unknown', True,
                                    'technology_or_role_experience_not_verified', scoped_required))
    return result


def _degree(profile, segments):
    positive, waived = [], []
    for item in segments:
        text = _text(item)
        seen_local = set()
        for match in _DEGREE.finditer(text):
            local = _local_text(text, match)
            if local in seen_local:
                continue
            seen_local.add(local)
            if re.search(r'\b(?:currently pursuing|pursuing|in progress|en curso|cursando|estudiante)\b', local):
                waived.append(item)
            else:
                if _negated(text, match):
                    waived.append(item)
                else:
                    positive.append((item, local))
    if not positive:
        return _requirement('completed_degree', 'not_required', False, 'degree_not_mandatory', waived)
    mandatory = [(item, local) for item, local in positive if not _PREFERRED.search(local)]
    facts = mandatory or positive
    alternative = all(re.search(r'\b(?:or equivalent experience|o experiencia equivalente|'
                                 r'or equivalent practical experience)\b', local) for _, local in facts)
    if mandatory and waived:
        status, reason = 'contradictory', 'conflicting_degree_requirements'
    elif alternative:
        equivalent = profile.conditions.get('equivalent_experience')
        if profile.degree_completed is True or equivalent is True:
            status, reason = 'met', 'degree_or_equivalent_satisfied'
        elif profile.degree_completed is False and equivalent is False:
            status, reason = 'unmet', 'degree_and_equivalent_experience_missing'
        else:
            status, reason = 'unknown', 'equivalent_experience_not_verified'
    elif profile.degree_completed is None:
        status, reason = 'unknown', 'candidate_degree_unknown'
    else:
        status = 'met' if profile.degree_completed else 'unmet'
        reason = 'completed_degree_verified' if status == 'met' else 'completed_degree_missing'
    evidence = [item for item, _ in facts] + waived
    if profile.degree_completed is not None:
        evidence.append(_profile_evidence('degree_completed', profile.degree_completed))
    if alternative and profile.conditions.get('equivalent_experience') is not None:
        evidence.append(_profile_evidence('conditions.equivalent_experience', profile.conditions['equivalent_experience']))
    return _requirement('completed_degree', status, bool(mandatory), reason, evidence,
                        alternative_available=alternative)


def _seniority(profile, segments):
    titles = [item for item in segments if item['field'] == 'title']
    senior = [item for item in titles if any(not _negated(_text(item), m) for m in _SENIOR.finditer(_text(item)))]
    if not senior:
        return _requirement('seniority', 'not_required', False, 'no_exclusive_senior_level_found')
    mixed = any(_JUNIOR.search(_text(item)) for item in senior)
    accepted = any(contains_phrase(value, term) for value in profile.accepted_seniority
                   for term in ('senior', 'lead', 'principal', 'manager', 'director'))
    status = 'unknown' if mixed or not profile.accepted_seniority else ('met' if accepted else 'unmet')
    return _requirement('seniority', status, True,
                        'seniority_ambiguous' if status == 'unknown' else 'seniority_accepted' if accepted else 'seniority_incompatible',
                        senior + [_profile_evidence('accepted_seniority', profile.accepted_seniority)])


def _languages(profile, segments):
    result = []
    for language, aliases in _LANGUAGES.items():
        facts, waived = [], []
        for item in segments:
            text = _text(item)
            terms = [*aliases, *(['bilingual', 'bilingue'] if language == 'english' else [])]
            pattern = r'\b(?:' + '|'.join(terms) + r')\b'
            seen_local = set()
            for match in re.finditer(pattern, text):
                local = _local_text(text, match)
                if local in seen_local:
                    continue
                seen_local.add(local)
                if _negated(text, match):
                    waived.append(item)
                else:
                    facts.append((item, local))
        if not facts and not waived:
            continue
        if not facts:
            result.append(_requirement('language_' + language, 'not_required', False, 'language_not_required', waived))
            continue
        mandatory = [(item, local) for item, local in facts if not _PREFERRED.search(local)]
        relevant = mandatory or facts
        minimum = 0
        for _, text in relevant:
            level = re.search(r'\b(a1|a2|b1|b2|c1|c2|advanced|avanzad[oa]|fluent|fluido|native|nativo)\b', text)
            if level:
                word = level.group(1)
                minimum = max(minimum, 5 if word in ('avanzado', 'avanzada', 'fluido') else 6 if word == 'nativo' else _LEVELS[word])
        known = any(any(contains_phrase(value, alias) for alias in aliases) for value in profile.languages)
        level_fact = next(((name, value) for name, value in profile.language_levels.items()
                           if any(contains_phrase(name, alias) for alias in aliases)), None)
        if mandatory and waived:
            status, reason = 'contradictory', 'conflicting_language_requirements'
        elif minimum:
            if level_fact is None:
                status, reason = 'unknown', 'language_level_unknown'
            else:
                status = 'met' if _LEVELS[normalize(level_fact[1])] >= minimum else 'unmet'
                reason = 'language_level_sufficient' if status == 'met' else 'language_level_below_minimum'
        else:
            status = 'met' if known or level_fact else 'unknown'
            reason = 'language_declared' if status == 'met' else 'candidate_language_unknown'
        evidence = [item for item, _ in relevant] + waived
        if level_fact:
            evidence.append(_profile_evidence('language_levels.' + level_fact[0], level_fact[1]))
        elif known:
            evidence.append(_profile_evidence('languages', profile.languages))
        result.append(_requirement('language_' + language, status, bool(mandatory), reason, evidence))
    return result


def _conditions(profile, segments):
    grouped: dict[str, list[tuple[dict, bool, bool]]] = {}
    for base_name, pattern in _CONDITIONS.items():
        for item in segments:
            text = _text(item)
            for match in re.finditer(pattern, text):
                local = _local_text(text, match)
                if not (_REQUIREMENT.search(text) or _PREFERRED.search(text)):
                    continue
                name = base_name
                if base_name == 'certification':
                    specific = re.search(r'\b(aws|azure|cissp|ccna|pmp)\b', local)
                    if specific:
                        name = specific.group(1) + '_certification'
                elif base_name == 'security_clearance' and 'top secret' in local:
                    name = 'top_secret_clearance'
                optional = bool(_PREFERRED.search(local))
                grouped.setdefault(name, []).append((item, optional, _negated(text, match)))
    result = []
    for name, facts in grouped.items():
        positive = [item for item, _, negated in facts if not negated]
        mandatory = [item for item, optional, negated in facts if not optional and not negated]
        waived = [item for item, _, negated in facts if negated]
        value = profile.conditions.get(name)
        if mandatory and waived:
            status = 'contradictory'
        elif not positive:
            status = 'not_required'
        else:
            status = 'unknown' if value is None else 'met' if value else 'unmet'
        evidence = (mandatory or positive) + waived
        if value is not None:
            evidence.append(_profile_evidence('conditions.' + name, value))
        result.append(_requirement(name, status, bool(mandatory), 'condition_' + status, evidence))
    # Check conjuncts separately: a recognized requirement cannot swallow an
    # unrelated mandatory fact in the same sentence. Qualifiers stay local.
    extra = 0
    seen_skills = set()
    for item in segments:
        text = _text(item)
        if not _REQUIREMENT.search(text):
            continue
        for part in _FACT_SEPARATOR.split(text):
            if not part.strip() or _PREFERRED.search(part):
                continue
            if any(re.search(pattern, part) for pattern in _CONDITIONS.values()):
                continue
            if re.search(r'\b(?:authorized to work|work authorization|permiso de trabajo|autorizad[oa] para trabajar)\b', part):
                continue
            if _GEOGRAPHIC_RESTRICTION.search(part) or _GEOGRAPHIC_WAIVER.search(part):
                # The geographic rule already owns these predicates, including
                # waivers. Do not invent a second unsupported obligation.
                continue
            if (_DEGREE.search(part) or _YEARS.search(part) or _REMOTE.search(part) or _NONREMOTE.search(part)
                    or re.search(r'\b(?:no experience|sin experiencia|no se requiere experiencia)\b', part)):
                continue
            unsupported = bool(re.search(r'\b(?:experience|experiencia|licen[cs]e|licencia)\b', part))
            languages = any(contains_phrase(part, alias) for aliases in _LANGUAGES.values() for alias in aliases)
            if languages and not unsupported:
                continue
            if any(contains_phrase(part, term) for term in profile.deal_breakers + list(SUSPICIOUS_TERMS)):
                continue
            skills = [skill for skill in COMMON_TECH_SKILLS if contains_phrase(part, skill)]
            if skills and not unsupported:
                for skill in skills:
                    if skill in seen_skills:
                        continue
                    seen_skills.add(skill)
                    owned = any(contains_phrase(skill, term) for owned in profile.skills
                                for term in [owned, *profile.skill_aliases.get(owned, [])])
                    result.append(_requirement('skill_' + re.sub(r'\W+', '_', skill),
                                                'met' if owned else 'unknown', True,
                                                'required_skill_declared' if owned else 'required_skill_not_verified',
                                                [item] + ([_profile_evidence('skills', profile.skills)] if owned else [])))
            else:
                extra += 1
                result.append(_requirement(f'additional_requirement_{extra}', 'unknown', True,
                                            'unsupported_mandatory_requirement', [item]))
    return result


def _work_authorization(profile, segments):
    authorization = re.compile(r'\b(?:authorized to work|work authorization|permiso de trabajo|autorizad[oa] para trabajar)\b')
    countries = {
        'MX': r'\bmexico\b', 'US': r'\b(?:united states|estados unidos|us|u\.s\.?)\b',
        'CA': r'\bcanada\b', 'GB': r'\b(?:uk|united kingdom|reino unido)\b',
        'DE': r'\b(?:germany|alemania)\b', 'ES': r'\b(?:spain|espana)\b',
    }
    grouped: dict[str, list[tuple[dict, bool, bool, list[str]]]] = {}
    for item in segments:
        text = _text(item)
        for match in authorization.finditer(text):
            local = _local_text(text, match)
            if not (_REQUIREMENT.search(text) or _PREFERRED.search(text)):
                continue
            codes = [code for code, pattern in countries.items() if re.search(pattern, local)]
            key = codes[0].lower() if len(codes) == 1 else 'alternatives' if codes else 'unknown'
            grouped.setdefault(key, []).append((item, bool(_PREFERRED.search(local)),
                                                _negated(text, match), codes))
    result = []
    for key, facts in grouped.items():
        affirmative = [(item, codes) for item, _, negative, codes in facts if not negative]
        mandatory = [item for item, optional, negative, _ in facts if not optional and not negative]
        waived = [item for item, _, negative, _ in facts if negative]
        value = profile.work_authorized_countries
        if mandatory and waived:
            status = 'contradictory'
        elif not affirmative:
            status = 'not_required'
        elif value is None or key in ('unknown', 'alternatives'):
            # Country lists can express alternatives or cumulative obligations;
            # preserve uncertainty instead of inventing that contract.
            status = 'unknown'
        else:
            status = 'met' if key.upper() in value else 'unmet'
        evidence = [item for item, _ in affirmative] + waived
        if value is not None:
            evidence.append(_profile_evidence('work_authorized_countries', value))
        result.append(_requirement('work_authorization_' + key, status, bool(mandatory),
                                    'candidate_work_authorization_' + status, evidence))
    return result


def _education_in_progress(profile, segments):
    evidence = [item for item in segments if re.search(
        r'\b(?:currently pursuing|pursuing|in progress|en curso|cursando|estudiante)\b', _text(item))
        and (_DEGREE.search(_text(item)) or re.search(r'\b(?:carrera|ingenieria)\b', _text(item)))
        and _REQUIREMENT.search(_text(item))]
    if not evidence:
        return []
    value = profile.conditions.get('degree_in_progress')
    status = 'unknown' if value is None else 'met' if value else 'unmet'
    if value is not None:
        evidence.append(_profile_evidence('conditions.degree_in_progress', value))
    return [_requirement('degree_in_progress', status, True, 'current_education_' + status, evidence)]


def _role_scope(segments):
    title = ' '.join(_text(item) for item in segments if item['field'] == 'title')
    evidence = [item for item in segments if item['field'] == 'title']
    technical = re.search(r'\b(?:technical support|application support|soporte tecnico|'
                          r'it support|help desk|engineer|developer|programador|ingeniero)\b', title)
    generic = re.search(r'\b(?:customer service|customer support|atencion al cliente|'
                        r'sales representative|sales executive|account executive|ventas|retencion|retention)\b', title)
    if generic and not technical:
        return _requirement('role_scope', 'unmet', True, 'excluded_generic_service_or_sales', evidence)
    return _requirement('role_scope', 'met' if technical else 'not_required', bool(technical),
                        'technical_role' if technical else 'no_excluded_role_confirmed', evidence if technical else [])


def _safety(profile, segments):
    result = []
    for category, terms in [('deal_breaker', profile.deal_breakers), ('suspicious', SUSPICIOUS_TERMS)]:
        for term in sorted(set(terms), key=str.casefold):
            facts = []
            pattern = re.compile(r'(?<!\w)' + re.escape(normalize(term)) + r'(?!\w)')
            for item in segments:
                text = _text(item)
                if any(not _negated(text, match) for match in pattern.finditer(text)):
                    facts.append(item)
            if facts:
                slug = re.sub(r'\W+', '_', normalize(term)).strip('_')
                result.append(_requirement(category + '_' + slug, 'unmet', True,
                                            category + ':' + term, facts))
    return result


def evaluate_eligibility(profile: CandidateProfile, job: JobPosting | NormalizedJob) -> list[dict[str, Any]]:
    """Evaluate exclusionary facts before any compatibility score is assigned."""
    segments = job_segments(job)
    result = [_mexico(segments), _remote(profile, segments), *_experience(profile, segments),
              _degree(profile, segments), _seniority(profile, segments), *_languages(profile, segments),
              *_conditions(profile, segments), *_work_authorization(profile, segments),
              *_education_in_progress(profile, segments), _role_scope(segments), *_safety(profile, segments)]
    salary = [item for item in segments if re.search(r'\b(?:salary|sueldo|salario|compensation|mxn|usd)\b|\$', _text(item))]
    result.append(_requirement('salary_information', 'unknown', False,
                               'salary_terms_require_review' if salary else 'salary_not_published', salary))
    return result
