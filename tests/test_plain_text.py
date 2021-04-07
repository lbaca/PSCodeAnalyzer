"""Plain text analysis tests."""

import os.path
import pscodeanalyzer.engine as psca


_TESTS_DIR = os.path.dirname(__file__)
_SETTINGS_FILE = os.path.join(_TESTS_DIR, psca.default_config_file_name)


def test_plain_text():
    """Test a plain text file for miscellaneous issues."""
    source_file = os.path.join(_TESTS_DIR, 'plain_text_sample.txt')
    file_reports = psca.analyze([source_file], _SETTINGS_FILE,
                                profile='test_04')
    reports = file_reports[0].reports
    # The elements of the found_errors and expected_errors sets are
    # tuples with two elements: (<rule code>, <line>)
    found_errors = {(r.rule_code, r.line) for r in reports}
    expected_errors = {
        (4, 7),
        (5, None),
        (6, 3),
    }
    undetected_errors = expected_errors - found_errors
    assert len(undetected_errors) == 0, \
        f'Undetected errors: {undetected_errors}'
    unexpected_errors = found_errors - expected_errors
    assert len(unexpected_errors) == 0, \
        f'Unexpected errors: {unexpected_errors}'
