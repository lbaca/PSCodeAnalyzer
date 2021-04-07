"""PeopleCode analysis tests."""

import os.path
import pscodeanalyzer.engine as psca


_TESTS_DIR = os.path.dirname(__file__)
_SETTINGS_FILE = os.path.join(_TESTS_DIR, psca.default_config_file_name)


def test_app_class_1():
    """Test an Application Class for SQLExec issues."""
    source_file = (os.path.join(_TESTS_DIR, 'HRMH_SETUP.HRMHServices.ppl'), 58)
    file_reports = psca.analyze([source_file], _SETTINGS_FILE,
                                profile='test_01')
    reports = file_reports[0].reports
    found_errors = {r.line for r in reports}
    expected_errors = {
        755,
        980,
        1230,
        1232,
        1275,
        1281,
        1392,
        1410,
        1416,
        1443,
        1449,
        1572,
        2004,
        2372,
        3459,
        3602,
        3635,
        3758,
        3819,
        4289,
        4304,
        4321,
        4400,
        4408,
        4432,
        4434,
    }
    undetected_errors = expected_errors - found_errors
    assert len(undetected_errors) == 0, \
        f'Undetected errors on line(s) {undetected_errors}'
    unexpected_errors = found_errors - expected_errors
    assert len(unexpected_errors) == 0, \
        f'Unexpected errors on line(s) {unexpected_errors}'


def test_program_1():
    """Test for SQLExec issues and undeclared variables."""
    source_file = (
        os.path.join(_TESTS_DIR, 'PTPG_WORKREC.FUNCLIB.FieldFormula.ppl'),
        None,
        [(850, 853)]
    )
    file_reports = psca.analyze([source_file], _SETTINGS_FILE,
                                profile='test_02')
    reports = file_reports[0].reports
    # The elements of the found_errors and expected_errors sets are
    # tuples with three elements: (<rule code>, <line>, <column>)
    found_errors = {(r.rule_code, r.line, r.column) for r in reports}
    expected_errors = {
        (1, 852, 13),
        (2, 850, 16),
        (2, 850, 37),
        (2, 850, 78),
        (2, 850, 95),
        (2, 852, 225),
        (2, 852, 246),
        (2, 852, 288),
        (2, 852, 309),
        (2, 852, 351),
        (2, 852, 372),
        (2, 852, 414),
        (2, 852, 435),
        (2, 852, 477),
        (2, 852, 498),
        (2, 853, 21),
        (2, 853, 42),
    }
    undetected_errors = expected_errors - found_errors
    assert len(undetected_errors) == 0, \
        f'Undetected errors: {undetected_errors}'
    unexpected_errors = found_errors - expected_errors
    assert len(unexpected_errors) == 0, \
        f'Unexpected errors: {unexpected_errors}'


def test_variables():
    """Test for naming convention violations.

    This test is an absurd example for documentation purposes.
    """
    source_file = os.path.join(_TESTS_DIR, 'variable_names.ppl')
    file_reports = psca.analyze([source_file], _SETTINGS_FILE,
                                profile='test_03')
    reports = file_reports[0].reports
    # The elements of the found_errors and expected_errors sets are
    # tuples with two elements: (<line>, <column>)
    found_errors = {(r.line, r.column) for r in reports}
    expected_errors = {
        (1, 14),
        (3, 14),
        (3, 21),
        (3, 28),
        (4, 14),
        (5, 14),
        (7, 15),
        (8, 21),
        (9, 15),
        (9, 28),
    }
    undetected_errors = expected_errors - found_errors
    assert len(undetected_errors) == 0, \
        f'Undetected errors: {undetected_errors}'
    unexpected_errors = found_errors - expected_errors
    assert len(unexpected_errors) == 0, \
        f'Unexpected errors: {unexpected_errors}'
