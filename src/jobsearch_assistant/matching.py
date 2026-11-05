"""Explainable compatibility scoring; eligibility always controls classification."""
from __future__ import annotations

from .eligibility import affirmed_phrase, evaluate_eligibility, job_segments
from .evaluator import COMMON_TECH_SKILLS, JUNIOR_TERMS, contains_phrase, matching_phrases
from .models import CandidateProfile, EvaluationResult, JobPosting
from .sources.models import NormalizedJob

ALGORITHM_VERSION = 'matching_v8'


def evaluate_match(profile: CandidateProfile, job: JobPosting | NormalizedJob) -> EvaluationResult:
    requirements = evaluate_eligibility(profile, job)
    by_name = {item['name']: item for item in requirements}
    segments = job_segments(job)
    matched = [skill for skill in profile.skills if any(affirmed_phrase(item, term)
               for item in segments for term in [skill, *profile.skill_aliases.get(skill, [])])]
    requested = [skill for skill in COMMON_TECH_SKILLS if any(affirmed_phrase(item, skill) for item in segments)]
    missing = [skill for skill in requested if not any(contains_phrase(skill, term)
               for owned in profile.skills for term in [owned, *profile.skill_aliases.get(owned, [])])]
    roles = sorted({role for role in profile.target_roles if any(affirmed_phrase(item, role) for item in segments)}, key=str.casefold)
    positive, reasons, risks = [], [], []
    score = 0
    scoring_evidence = []

    def award(name, points, signal, facts):
        nonlocal score
        score += points
        reasons.append(f'points:{name}:{points}')
        if signal:
            positive.append(signal)
        scoring_evidence.extend({'component': name, 'signal': signal, **fact} for fact in facts)

    if profile.skills:
        points = min(35, round(35 * len(matched) / len(profile.skills)))
        reasons.append(f'skills:{len(matched)}/{len(profile.skills)}')
        if points:
            facts = [item for item in segments if any(affirmed_phrase(item, term)
                     for skill in matched for term in [skill, *profile.skill_aliases.get(skill, [])])]
            facts.append({'field': 'profile.skills', 'value': list(profile.skills),
                          'provenance': ['candidate_profile']})
            award('skills', points, 'skill_match', facts)
    if roles:
        award('role', 20, 'target_role', [item for item in segments if any(affirmed_phrase(item, role) for role in roles)])
    else:
        reasons.append('no_target_role_signal')
    junior = any(affirmed_phrase(item, term) for item in segments if item['field'] == 'title' for term in JUNIOR_TERMS)
    if junior and by_name['seniority']['status'] != 'unmet':
        award('seniority', 10, 'junior_friendly', [item for item in segments if item['field'] == 'title'
                                                and any(affirmed_phrase(item, term) for term in JUNIOR_TERMS)])
    if by_name['seniority']['status'] in ('unmet', 'met', 'unknown'):
        risks.append('senior_level')
    if by_name['remote_work']['status'] == 'met':
        award('remote', 10, 'remote_match', by_name['remote_work']['evidence'])
    elif profile.remote_only:
        risks.append('remote_not_confirmed')
    locations = ' '.join(job.locations) if isinstance(job, NormalizedJob) else job.location
    if matching_phrases(locations, profile.preferred_locations):
        award('location', 5, 'location_match', [item for item in segments
              if item['field'].startswith('location')
              and any(affirmed_phrase(item, place) for place in profile.preferred_locations)])
    if any(item['name'].startswith('language_') and item['status'] == 'met' for item in requirements):
        award('languages', 7, 'language_match', [fact for item in requirements
              if item['name'].startswith('language_') and item['status'] == 'met' for fact in item['evidence']])
    experience = by_name['experience']
    if experience['status'] == 'met':
        award('experience', 5, 'experience_requirement_accessible', experience['evidence'])
    if experience.get('minimum_years', 0) >= 5:
        years = f"{experience['minimum_years']:g}"
        risks.append(f'experience_requirement_{years}_years')
    if by_name['mexico_hiring']['status'] == 'met':
        award('mexico_hiring', 8, 'mexico_hiring_confirmed', by_name['mexico_hiring']['evidence'])
    for item in requirements:
        if item['reason_code'].startswith(('deal_breaker:', 'suspicious:')):
            risks.append(item['reason_code'])
    score = max(0, min(100, score))
    unmet = [r for r in requirements if r['required'] and r['status'] == 'unmet']
    unknown = [r for r in requirements if r['status'] in ('unknown', 'contradictory')]
    if unmet:
        recommendation = 'ineligible'
    elif any(r['required'] for r in unknown):
        recommendation = 'insufficient_information'
    elif any(r['name'] != 'salary_information' for r in unknown):
        recommendation = 'manual_review'
    elif score >= 80:
        recommendation = 'high_priority'
    elif score >= 65:
        recommendation = 'medium_priority'
    elif score >= 50:
        recommendation = 'manual_review'
    else:
        recommendation = 'rejected'
    evidence = []
    for item in requirements:
        evidence.extend({'requirement': item['name'], **fact} for fact in item['evidence'])
    evidence.extend(scoring_evidence)
    suggestions = ['verify:' + r['name'] for r in unknown]
    suggestions.extend('address:' + r['name'] for r in unmet)
    suggestions.extend('learn_or_document:' + skill for skill in missing)
    return EvaluationResult(
        score=score, recommendation=recommendation, matched_skills=matched, missing_skills=missing,
        role_signals=roles, positive_signals=sorted(set(positive)), risks=sorted(set(risks)),
        reasons=reasons, algorithm_version=ALGORITHM_VERSION, requirements=requirements,
        requirements_met=[r['name'] for r in requirements if r['status'] == 'met'],
        missing_requirements=[r['name'] for r in unmet],
        restrictions=[r['reason_code'] for r in unmet], unknowns=[r['name'] for r in unknown],
        evidence=evidence, suggestions=list(dict.fromkeys(suggestions)))


_LABELS = {
    'es': {'high_priority': 'Prioridad alta', 'medium_priority': 'Prioridad media',
           'manual_review': 'Revisión manual', 'rejected': 'Descartada',
           'ineligible': 'No elegible', 'insufficient_information': 'Información insuficiente'},
    'en': {'high_priority': 'High priority', 'medium_priority': 'Medium priority',
           'manual_review': 'Manual review', 'rejected': 'Rejected',
           'ineligible': 'Ineligible', 'insufficient_information': 'Insufficient information'},
}
_NAMES = {
    'mexico_hiring': ('Autorización del empleador para contratar desde México', 'Employer permission to hire from Mexico'),
    'remote_work': ('Trabajo remoto', 'Remote work'),
    'experience': ('Experiencia obligatoria', 'Required experience'),
    'preferred_experience': ('Experiencia deseable', 'Preferred experience'),
    'scoped_experience': ('Experiencia específica sin verificar', 'Unverified technology or role experience'),
    'completed_degree': ('Título terminado o alternativa aceptada', 'Completed degree or accepted alternative'),
    'seniority': ('Nivel del puesto', 'Role seniority'),
    'role_scope': ('Tipo de puesto', 'Role scope'),
    'salary_information': ('Salario pendiente de verificar', 'Salary pending verification'),
    'security_clearance': ('Habilitación de seguridad', 'Security clearance'),
    'weekend_work': ('Trabajo en fines de semana', 'Weekend work'),
    'travel': ('Disponibilidad para viajar', 'Travel availability'),
    'driver_license': ('Licencia de conducir', 'Driving license'),
    'certification': ('Certificación', 'Certification'),
    'work_authorization_mx': ('Permiso del candidato para trabajar en México', 'Candidate permission to work in Mexico'),
    'work_authorization_us': ('Permiso para trabajar en Estados Unidos', 'Permission to work in the United States'),
    'work_authorization_ca': ('Permiso para trabajar en Canadá', 'Permission to work in Canada'),
    'work_authorization_gb': ('Permiso para trabajar en Reino Unido', 'Permission to work in the United Kingdom'),
    'work_authorization_de': ('Permiso para trabajar en Alemania', 'Permission to work in Germany'),
    'work_authorization_es': ('Permiso para trabajar en España', 'Permission to work in Spain'),
    'work_authorization_unknown': ('Permiso laboral sin país reconocido', 'Work authorization for an unrecognized country'),
    'work_authorization_alternatives': ('Permisos laborales con condiciones ambiguas', 'Work authorizations with ambiguous conditions'),
    'degree_in_progress': ('Estudios actualmente en curso', 'Current enrollment in degree studies'),
}
_LANGUAGE_NAMES = {'english': 'inglés', 'spanish': 'español', 'french': 'francés',
                   'german': 'alemán', 'portuguese': 'portugués', 'italian': 'italiano',
                   'japanese': 'japonés', 'mandarin': 'mandarín'}


def _name(name: str, language: str) -> str:
    if name in _NAMES:
        return _NAMES[name][0 if language == 'es' else 1]
    if name.startswith('language_'):
        key = name.removeprefix('language_')
        return ('Idioma: ' + _LANGUAGE_NAMES.get(key, key)) if language == 'es' else 'Language: ' + key
    if name.startswith('additional_requirement_'):
        return 'Requisito adicional sin verificar' if language == 'es' else 'Additional unverified requirement'
    return name.replace('_', ' ')


def explain_evaluation(result: EvaluationResult, language: str = 'es') -> str:
    """Render the same evidence for both interfaces, without hiring predictions."""
    language = 'en' if language == 'en' else 'es'
    spanish = language == 'es'
    label = _LABELS[language].get(result.recommendation, result.recommendation)
    lines = [f'{label} — {result.score}/100',
             ('Algoritmo: ' if spanish else 'Algorithm: ') + result.algorithm_version,
             ('Puntuación interna de compatibilidad; no es una probabilidad de contratación.' if spanish
              else 'Internal compatibility score; it is not a hiring probability.')]
    groups = [('Cumplidos' if spanish else 'Met', result.requirements_met),
              ('Incumplidos' if spanish else 'Unmet', result.missing_requirements),
              ('Información pendiente' if spanish else 'Information pending', result.unknowns)]
    for heading, names in groups:
        if names:
            lines.append(heading + ': ' + '; '.join(_name(name, language) for name in names) + '.')
    if result.restrictions:
        lines.append(('Motivos de exclusión: ' if spanish else 'Exclusion reasons: ') + '; '.join(result.restrictions))
    if result.matched_skills:
        lines.append(('Habilidades declaradas coincidentes: ' if spanish else 'Matching declared skills: ') + ', '.join(result.matched_skills))
    if result.reasons:
        lines.append(('Desglose de puntos: ' if spanish else 'Score details: ') + '; '.join(result.reasons))
    if result.evidence:
        lines.append('Evidencia:' if spanish else 'Evidence:')
        seen = set()
        for fact in result.evidence:
            if 'span' not in fact:
                continue
            key = (fact['field'], fact['span'])
            if key not in seen:
                seen.add(key)
                lines.append(f"- {fact['field']}: {fact['span']}")
    if result.suggestions:
        lines.append('Siguientes pasos:' if spanish else 'Next steps:')
        for suggestion in result.suggestions:
            action, _, name = suggestion.partition(':')
            if action == 'verify':
                verb = 'Verificar' if spanish else 'Verify'
            elif action == 'address':
                verb = 'Revisar el incumplimiento de' if spanish else 'Review the unmet requirement for'
            else:
                verb = 'Aprender o documentar honestamente' if spanish else 'Learn or truthfully document'
            lines.append(f'- {verb} {_name(name, language)}.')
    return '\n'.join(lines)
