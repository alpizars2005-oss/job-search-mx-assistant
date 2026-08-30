from jobsearch_assistant.exporters import _csv_safe


def test_csv_safe_neutralizes_formula_prefixes():
    for value in ("=2+2", "+SUM(A1:A2)", "-1+1", "@cmd", "\tformula", "\rformula"):
        assert _csv_safe(value) == "'" + value


def test_csv_safe_preserves_normal_text_and_numbers():
    assert _csv_safe("Software Engineer") == "Software Engineer"
    assert _csv_safe("https://example.com/job") == "https://example.com/job"
    assert _csv_safe(95) == 95
