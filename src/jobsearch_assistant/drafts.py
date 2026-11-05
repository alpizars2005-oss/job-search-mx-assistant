"""Literal bilingual composition from the selected, evidence-backed CV facts."""
from __future__ import annotations

from .sources.models import NormalizedJob
from .workflow_contracts import WorkflowError

_HEADINGS = {
    'es': {'experience': 'Experiencia', 'project': 'Proyectos personales',
           'certification': 'Certificaciones', 'education': 'Formación', 'skill': 'Habilidades'},
    'en': {'experience': 'Experience', 'project': 'Personal projects',
           'certification': 'Certifications', 'education': 'Education', 'skill': 'Skills'},
}


def build_draft(job: NormalizedJob, version: dict) -> str:
    """Use literal declared facts; never infer qualifications from the vacancy."""
    language = version.get('language')
    claims = version.get('claims')
    name = version.get('candidate_name')
    if language not in _HEADINGS or not isinstance(name, str) or not name.strip() or not claims:
        raise WorkflowError('missing_verified_resume_facts')
    title = job.title or ('la vacante publicada' if language == 'es' else 'the advertised role')
    introduction = (f'Me interesa {title} en {job.company}.' if language == 'es'
                    else f'I am interested in {title} at {job.company}.')
    lines = [introduction]
    for kind, heading in _HEADINGS[language].items():
        facts = [claim for claim in claims if claim.get('kind') == kind]
        if facts:
            lines.extend(('', heading + ':'))
            for fact in facts:
                text = fact.get('text')
                if not isinstance(text, str) or not text.strip() or not fact.get('evidence_ids'):
                    raise WorkflowError('missing_verified_resume_facts')
                lines.append('- ' + text)
    lines.extend(('', name))
    return '\n'.join(lines) + '\n'
