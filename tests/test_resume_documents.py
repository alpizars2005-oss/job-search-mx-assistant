import importlib
import io
import unittest
import xml.etree.ElementTree as ET
import zipfile


class ResumeDocumentTests(unittest.TestCase):
    def renderer(self):
        try:
            return importlib.import_module('jobsearch_assistant.resume_documents').render_document
        except ModuleNotFoundError:
            self.fail('Deterministic resume document renderer is not implemented')

    def test_txt_is_exact_utf8(self):
        self.assertEqual(self.renderer()('Nombre\nMéxico & <Python>\n', 'txt'),
                         b'Nombre\nM\xc3\xa9xico & <Python>\n')

    def test_docx_is_reproducible_text_only_ooxml_with_escaped_literal_text(self):
        render = self.renderer()
        text = 'Nombre\nMéxico & <Python>\n\nProjects\nPersonal project.\n'
        document = render(text, 'docx')
        self.assertEqual(document, render(text, 'docx'))
        with zipfile.ZipFile(io.BytesIO(document)) as archive:
            self.assertEqual(set(archive.namelist()),
                             {'[Content_Types].xml', '_rels/.rels', 'word/document.xml'})
            for member in archive.infolist():
                self.assertEqual(member.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(member.compress_type, zipfile.ZIP_STORED)
            relationships = ET.fromstring(archive.read('_rels/.rels'))
            self.assertEqual(len(relationships), 1)
            self.assertEqual(relationships[0].attrib['Target'], 'word/document.xml')
            self.assertNotIn('TargetMode', relationships[0].attrib)
            root = ET.fromstring(archive.read('word/document.xml'))
            namespace = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            paragraphs = root.findall('.//w:p', namespace)
            extracted = '\n'.join(''.join(p.itertext()) for p in paragraphs) + '\n'
            self.assertEqual(extracted, text)

    def test_renderer_rejects_invalid_formats_and_xml_controls(self):
        from jobsearch_assistant.workflow_contracts import WorkflowError
        for text, fmt in [('private', 'pdf'), ('private\x00', 'docx'), (None, 'txt')]:
            with self.subTest(format=fmt), self.assertRaises(WorkflowError):
                self.renderer()(text, fmt)


if __name__ == '__main__':
    unittest.main()
