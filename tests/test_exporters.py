import unittest

from jobsearch_assistant.exporters import _csv_safe


class CsvSafetyTests(unittest.TestCase):
    def test_csv_safe_neutralizes_formula_prefixes(self):
        for value in ('=2+2', '+SUM(A1:A2)', '-1+1', '@cmd', '\tformula', '\rformula'):
            with self.subTest(value=value):
                self.assertEqual(_csv_safe(value), "'" + value)

    def test_csv_safe_preserves_normal_text_and_numbers(self):
        self.assertEqual(_csv_safe('Software Engineer'), 'Software Engineer')
        self.assertEqual(_csv_safe('https://example.com/job'), 'https://example.com/job')
        self.assertEqual(_csv_safe(95), 95)
