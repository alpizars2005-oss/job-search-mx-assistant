"""Reproducible UTF-8 and text-only OpenXML documents; no office dependency."""
from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from .workflow_contracts import WorkflowError


def valid_document_text(value: object) -> bool:
    """Only XML 1.0 text, with LF as the sole embedded control character."""
    return type(value) is str and all(
        char == '\n' or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF
        for char in value
    )


def render_document(text: str, format: str) -> bytes:
    """Render the exact same plain text, with fixed ZIP metadata on all platforms."""
    if not valid_document_text(text) or len(text) > 1024 * 1024:
        raise WorkflowError('invalid_resume_text')
    if format == 'txt':
        return text.encode('utf-8')
    if format != 'docx':
        raise WorkflowError('invalid_resume_format')
    # A trailing LF represents the end of the last paragraph, not another one.
    lines = text[:-1].split('\n') if text.endswith('\n') else text.split('\n')
    paragraphs = ''.join(
        '<w:p><w:r><w:t xml:space="preserve">' + escape(line) + '</w:t></w:r></w:p>'
        for line in lines
    )
    parts = {
        '[Content_Types].xml': (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>'
        ),
        '_rels/.rels': (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>'
        ),
        'word/document.xml': (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>' + paragraphs + '<w:sectPr/></w:body></w:document>'
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, value in parts.items():
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 0
            member.external_attr = 0o600 << 16
            archive.writestr(member, value.encode('utf-8'))
    return buffer.getvalue()
